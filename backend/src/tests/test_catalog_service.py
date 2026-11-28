import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.disk.entities import NTFSVolume
from infrastructure.filesystems.ntfs.catalog_builder import CatalogContentValidator
from infrastructure.filesystems.ntfs.catalog_builder import CatalogBuilder
from infrastructure.storage.image.reader import RawImageReader
from infrastructure.filesystems.ntfs.readers.content_reference_reader import NTFSContentReferenceReader
from helpers import make_recovery_workflow
from helpers import make_record
from types import SimpleNamespace


class FakeDisk:
    def __init__(self, _disk_number):
        self.closed = False
        self.size = 16384
        self.reads = []
        self.data = bytearray(self.size)

    def read_at(self, offset, size):
        self.reads.append((offset, size))
        return bytes(self.data[offset:offset + size])

    def close(self):
        self.closed = True


def jpeg(payload=b"entropy-data"):
    return (b"\xff\xd8\xff\xe0\x00\x04\x00\x00"
        + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        + payload.replace(b"\xff", b"\xff\x00") + b"\xff\xd9")


class CatalogServiceTests(unittest.TestCase):
    def test_ntfs_catalog_reads_a_raw_image_without_a_physical_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = os.path.join(directory, "fixture.img")
            image = bytearray(8192)
            image[4096:4096 + 1024] = make_record("image.pdf", b"%PDF-image")
            with open(image_path, "wb") as image_file:
                image_file.write(image)

            volume = NTFSVolume(
                0, 1, 0, len(image), 512, 4096, 1024, 4096, 1024,
                ((4096, 1, 0),),
            )
            snapshot = CatalogBuilder(lambda _number: RawImageReader(image_path)).build(volume)

        self.assertEqual(len(snapshot.catalog.nodes), 1)
        node = next(iter(snapshot.catalog.nodes.values()))
        self.assertEqual(node.name, "image.pdf")
        self.assertEqual(node.candidate.size_bytes, len(b"%PDF-image"))

    def test_builds_empty_catalog_and_closes_disk_reader(self):
        opened = []

        def disk_factory(disk_number):
            disk = FakeDisk(disk_number)
            opened.append(disk)
            return disk

        volume = NTFSVolume(3, 1, 0, 8192, 512, 4096, 1024, 0, 0, ())
        snapshot = CatalogBuilder(disk_factory).build(volume)

        self.assertTrue(snapshot.volume_id)
        self.assertEqual(snapshot.filesystem_id, "ntfs")
        self.assertEqual(snapshot.catalog.nodes, {})
        self.assertEqual(snapshot.catalog.root_nodes, [])
        self.assertTrue(opened[0].closed)

    def test_orphan_header_validation_reads_only_a_bounded_signature_window(self):
        disk = FakeDisk(3)
        disk.data[8192:8200] = b"\xff\xd8\xffphoto"
        record = SimpleNamespace(
            name="photo.jpg", file_size=8 * 1024 * 1024,
            resident_data=None, data_runs=((2, 1),), data_is_complete=True,
        )

        result = CatalogContentValidator(disk, 0, disk.size, 4096).validate(record)

        self.assertEqual(result.status, "signature_match")
        self.assertEqual(disk.reads, [(8192, 8)])

    def test_orphan_header_validation_does_not_accept_a_mismatched_signature(self):
        disk = FakeDisk(3)
        disk.data[4096:4104] = b"not-a-jp"
        record = SimpleNamespace(
            name="photo.jpg", file_size=4096,
            resident_data=None, data_runs=((1, 1),), data_is_complete=True,
        )

        result = CatalogContentValidator(disk, 0, disk.size, 4096).validate(record)

        self.assertEqual(result.status, "signature_mismatch")
        self.assertEqual(disk.reads, [(4096, 8)])

    def test_orphan_header_validation_reports_unsupported_data_flags_without_reading(self):
        disk = FakeDisk(3)
        record = SimpleNamespace(
            name="photo.jpg", file_size=4096,
            resident_data=None, data_runs=((1, 1),), data_is_complete=True,
            data_unsupported_reason="encrypted_data_is_unsupported",
        )

        result = CatalogContentValidator(disk, 0, disk.size, 4096).validate(record)

        self.assertEqual(result.status, "unsupported_data_attribute")
        self.assertEqual(result.reason, "encrypted_data_is_unsupported")
        self.assertEqual(disk.reads, [])

    def test_catalog_filters_only_known_signature_mismatches(self):
        bad = SimpleNamespace()
        uncertain = SimpleNamespace()

        class Validator:
            def validate(self, record):
                status = "signature_mismatch" if record is bad else "unavailable"
                return SimpleNamespace(status=status, reason=status)

        remaining = CatalogBuilder._validate_orphan_content(
            {-1: bad, -2: uncertain}, Validator(),
        )

        self.assertEqual(remaining, {-2: uncertain})
        self.assertEqual(bad.catalog_content_validation, "signature_mismatch")
        self.assertEqual(uncertain.catalog_content_validation, "unavailable")

    def test_orphan_scan_is_opt_in_and_uses_the_selected_volume(self):
        opened = []
        volume = NTFSVolume(3, 1, 0, 8192, 512, 4096, 1024, 0, 0, ())

        def disk_factory(disk_number):
            disk = FakeDisk(disk_number)
            opened.append(disk)
            return disk

        with patch("infrastructure.filesystems.ntfs.catalog_builder.GhostMFTCarver") as carver_type:
            snapshot = CatalogBuilder(disk_factory).build(volume, include_orphaned=True)

        carver_type.assert_called_once_with(opened[0])
        carver_type.return_value.hunt.assert_called_once()
        self.assertEqual(carver_type.return_value.hunt.call_args.args[0], volume)
        self.assertTrue(snapshot.orphan_scan_performed)
        self.assertTrue(opened[0].closed)

    def test_reuses_audited_orphan_records_instead_of_scanning_the_volume_again(self):
        volume = NTFSVolume(3, 1, 0, 8192, 512, 4096, 1024, 0, 0, ())
        opened = []
        orphan = SimpleNamespace(
            index=-101, mft_offset=100, name="photo.jpg", is_dir=False,
            is_allocated=False, file_size=1, raw_data=b"unique", is_valid=True,
        )

        def disk_factory(disk_number):
            disk = FakeDisk(disk_number)
            opened.append(disk)
            return disk

        with patch("infrastructure.recovery.extractor.Extractor.supported_extensions", return_value=(".jpg",)):
            with patch("infrastructure.filesystems.ntfs.catalog_builder.GhostMFTCarver") as carver_type:
                snapshot = CatalogBuilder(disk_factory).build(
                    volume,
                    include_orphaned=True,
                    precomputed_orphans={-101: orphan},
                )

        carver_type.assert_not_called()
        candidate = next(iter(snapshot.catalog.nodes.values())).candidate
        self.assertTrue(any(
            dict(evidence.details).get("recordNumber") == -101
            for evidence in candidate.evidence
        ))
        self.assertTrue(snapshot.catalog.nodes[candidate.candidate_id].properties["isOrphaned"])
        self.assertTrue(opened[0].closed)

    def test_adds_bounded_carved_jpeg_as_a_recoverable_catalog_candidate(self):
        volume = NTFSVolume(3, 1, 0, 8192, 512, 4096, 1024, 0, 0, ())
        disk = FakeDisk(3)
        candidate = jpeg()
        disk.data[4096:4096 + len(candidate)] = candidate

        builder = CatalogBuilder(lambda _number: disk)
        snapshot = builder.build(
            volume,
            include_orphaned=True,
            precomputed_orphans={},
            precomputed_carving_ranges=((4096, 8192),),
        )

        self.assertEqual(len(snapshot.catalog.nodes), 1)
        node = next(iter(snapshot.catalog.nodes.values()))
        self.assertTrue(node.properties["isContentCarved"])
        self.assertTrue(node.properties["isOrphaned"])
        self.assertEqual(node.properties["contentValidation"], "format_structure_match")
        self.assertEqual(node.candidate.content_reference.size_bytes, len(candidate))
        self.assertEqual(snapshot.content_carving_summary["filesFound"], 1)
        self.assertEqual(snapshot.content_carving_summary["bytesScanned"], 4096)
        self.assertEqual(snapshot.content_carving_summary["filesFoundByExtension"], {
            ".jpg": 1, ".png": 0, ".pdf": 0, ".office_zip": 0,
            ".mp4": 0, ".rtf": 0, ".ole_cfb": 0,
        })
        self.assertEqual(snapshot.content_carving_summary["validationScope"],
            "contiguous_structure_and_signature")

        class OutputGuard:
            def validate_source(self, *_args):
                return []

        recovery = make_recovery_workflow(
            output_guard=OutputGuard(),
            content_reader_factory=lambda source: NTFSContentReferenceReader(
                lambda _source: FakeDisk(3), builder.content_reference_store,
            ),
        )
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with tempfile.TemporaryDirectory(dir=repo_root) as output_directory:
            summary = recovery.extract_selection(
                snapshot, [node], output_directory, {".jpg"},
            )
            recovered_path = os.path.join(
                output_directory, "Lost_Files_DeepScan", "ContentCarving", node.name,
            )
            with open(recovered_path, "rb") as recovered_file:
                self.assertEqual(recovered_file.read(), candidate)
        self.assertEqual(summary.recovered_count, 1)

    def test_catalog_forwards_resume_checkpoint_and_checkpoint_callback(self):
        volume = NTFSVolume(3, 1, 0, 8192, 512, 4096, 1024, 0, 0, ())
        disk = FakeDisk(3)
        candidate = jpeg()
        disk.data[4096:4096 + len(candidate)] = candidate
        saved_checkpoints = []
        options = SimpleNamespace(
            scan_budget_gib=1, max_files=10, max_retained_mib=256,
            max_candidate_read_mib_per_format=1024,
        )

        snapshot = CatalogBuilder(lambda _number: disk).build(
            volume,
            include_orphaned=True,
            precomputed_orphans={},
            precomputed_carving_ranges=((4096, 8192),),
            carving_options=options,
            carving_checkpoint_callback=saved_checkpoints.append,
        )

        self.assertEqual(snapshot.content_carving_summary["filesFound"], 1)
        self.assertEqual(snapshot.content_carving_summary["retainedBudgetMiB"], 256)
        self.assertEqual(snapshot.content_carving_summary["retainedBytesCap"], 256 * 1024**2)
        self.assertEqual(snapshot.content_carving_summary["candidateReadCapBytesPerFormat"], 1024 * 1024**2)
        self.assertEqual(snapshot.content_carving_summary["candidateReadCapBytes"], 3 * 1024 * 1024**2)
        self.assertEqual(saved_checkpoints[-1], None)
        self.assertFalse(snapshot.content_carving_summary["resumeAvailable"])

    def test_preserves_checkpoint_when_audited_free_ranges_were_truncated(self):
        volume = NTFSVolume(3, 1, 0, 8192, 512, 4096, 1024, 0, 0, ())
        disk = FakeDisk(3)
        saved_checkpoints = []

        snapshot = CatalogBuilder(lambda _number: disk).build(
            volume,
            include_orphaned=True,
            precomputed_orphans={},
            precomputed_carving_ranges=((4096, 8192),),
            carving_ranges_truncated=True,
            carving_checkpoint_callback=saved_checkpoints.append,
        )

        self.assertTrue(snapshot.content_carving_summary["rangeCollectionTruncated"])
        self.assertTrue(snapshot.content_carving_summary["resumeAvailable"])
        self.assertIsNotNone(saved_checkpoints[-1])
        self.assertEqual(saved_checkpoints[-1].next_offset, 8192)

    def test_keeps_bitmap_unobserved_candidates_separate_and_deduplicates_lower_tiers(self):
        volume = NTFSVolume(3, 1, 0, 16384, 512, 4096, 1024, 0, 0, ())
        disk = FakeDisk(3)
        candidate = jpeg()
        disk.data[4096:4096 + len(candidate)] = candidate
        uncertain_candidate = jpeg(b"uncertain-data")
        disk.data[8192:8192 + len(uncertain_candidate)] = uncertain_candidate

        snapshot = CatalogBuilder(lambda _number: disk).build(
            volume,
            include_orphaned=True,
            precomputed_orphans={},
            precomputed_carving_ranges=((4096, 8192),),
            precomputed_uncertain_carving_ranges={
                "bitmapUnobserved": ((8192, 12288),),
                "possiblyReused": ((8192, 12288),),
            },
            uncertain_carving_ranges_truncated={
                "bitmapUnobserved": False, "possiblyReused": False,
            },
        )

        nodes = list(snapshot.catalog.nodes.values())
        self.assertEqual(len(nodes), 2)
        uncertain_node = next(node for node in nodes
            if node.properties["clusterAllocationStatus"] == "bitmap_unobserved")
        self.assertTrue(uncertain_node.full_path.startswith(
            os.path.join("Lost_Files_DeepScan", "LowConfidence", "BitmapUnobserved"),
        ))
        self.assertFalse(uncertain_node.properties["isDeleted"])
        self.assertEqual(
            snapshot.low_confidence_carving_summary["bitmapUnobserved"]["catalogItemsAdded"], 1,
        )
        self.assertEqual(
            snapshot.low_confidence_carving_summary["possiblyReused"]["filesFound"], 1,
        )
        self.assertEqual(
            snapshot.low_confidence_carving_summary["possiblyReused"]["catalogItemsAdded"], 0,
        )


if __name__ == "__main__":
    unittest.main()
