import hashlib
import os
import random
import struct
import sys
import tempfile
import unittest
import zlib
from dataclasses import replace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(__file__))

from infrastructure.carving.content_carver import RawContentCarver
from infrastructure.carving.png_idat_fragment_reconstructor import PNGIDATFragmentReconstructor
from infrastructure.filesystems.ntfs.catalog_builder import CatalogBuilder
from infrastructure.filesystems.ntfs.readers.content_reference_reader import NTFSContentReferenceReader
from modules.catalog.dto import CarvingOptionsDto
from modules.catalog.mapper import CatalogMapper
from modules.disk.entities import NTFSVolume
from infrastructure.recovery.extractor import Extractor
from test_png_progressive_reconstruction_experiment import _parts_png


CLUSTER = 4096


class MemoryDisk:
    def __init__(self, data):
        self.data = bytes(data)
        self.size = len(self.data)
        self.bytes_per_sector = 512
        self.read_bytes = 0
        self.read_log = []
        self.closed = False

    def read_at(self, offset, size):
        self.read_bytes += size
        self.read_log.append((offset, size))
        return self.data[offset:offset + size]

    def close(self):
        self.closed = True


def _chunk(kind, payload=b""):
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))


def _fixture(seed=42, foreign=False):
    original, prefix, idats = _parts_png(8, 4, 2, level=3, seed=seed)
    slots = 6 if foreign else 4
    data = bytearray(b"\xa5" * (slots * CLUSTER))
    data[:len(prefix)] = prefix
    data[CLUSTER:CLUSTER + len(idats[0])] = idats[0]
    tail_slot = 3 if foreign else 2
    data[tail_slot * CLUSTER:tail_slot * CLUSTER + len(idats[1])] = idats[1]
    iend_slot = tail_slot + 1
    iend = _chunk(b"IEND")
    data[iend_slot * CLUSTER:iend_slot * CLUSTER + len(iend)] = iend
    if foreign:
        ancillary = _chunk(b"tEXt", b"foreign payload")
        data[2 * CLUSTER:2 * CLUSTER + len(ancillary)] = ancillary
    return original, bytes(data)


def _progressive_fixture(count, seed):
    original, prefix, idats = _parts_png(48, 32, count, level=3, seed=seed)
    chunks = list(idats)
    decoy_count = 1 if count == 4 else 2
    _, _, decoys = _parts_png(3, 2, decoy_count, level=1, seed=seed + 100)
    chunks.extend(decoys)
    chunks.append(_chunk(b"IEND"))
    random.Random(seed + 7).shuffle(chunks)
    data = bytearray(prefix)
    for chunk in chunks:
        target = ((len(data) + CLUSTER - 1) // CLUSTER) * CLUSTER
        data.extend(b"\xa5" * (target - len(data)))
        data.extend(chunk)
    return original, MemoryDisk(data), ((0, len(prefix)), (len(prefix), len(data)))


def _unique_read_bytes(read_log):
    intervals = sorted((start, start + size) for start, size in read_log if size)
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return sum(end - start for start, end in merged)


class PNGIDATFragmentReconstructorTests(unittest.TestCase):
    def test_two_complete_idat_chunks_recover_where_contiguous_carving_misses(self):
        original, data = _fixture(foreign=True)
        source = MemoryDisk(data)
        contiguous = RawContentCarver(source).scan(((0, len(data)),))
        contiguous_total = source.read_bytes
        contiguous_unique = _unique_read_bytes(source.read_log)
        source.read_log.clear()
        source.read_bytes = 0
        result = PNGIDATFragmentReconstructor(
            source, volume_start=0, volume_end=len(data), cluster_size=CLUSTER,
        ).reconstruct((0,), ((0, len(data)),))
        reconstructed_unique = _unique_read_bytes(source.read_log)

        self.assertFalse(any(item.extension == ".png" for item in contiguous.files))
        self.assertEqual(1, len(result.candidates))
        self.assertEqual(hashlib.sha256(original).hexdigest(),
                         hashlib.sha256(result.candidates[0].data).hexdigest())
        self.assertEqual("unique_hypothesis_in_scope",
                         result.candidates[0].evidence["hypothesisStatus"])
        self.assertEqual("search_exhausted", result.stop_reason)
        self.assertEqual(result.bytes_read, source.read_bytes)
        self.assertLess(result.bytes_read, contiguous_total)
        self.assertLessEqual(contiguous_unique, contiguous_total)
        self.assertLessEqual(reconstructed_unique, result.bytes_read)
        self.assertLessEqual(result.combinations, 256)
        self.assertLessEqual(result.bytes_read, 32 * 1024 * 1024)
        self.assertLessEqual(result.retained_bytes_estimate, 16 * 1024 * 1024)

    def test_three_and_four_complete_idat_chunks_match_the_phase_3c_oracle(self):
        for count, expected_pairs in ((3, 186), (4, 228)):
            with self.subTest(idat_chunks=count):
                original, source, ranges = _progressive_fixture(count, seed=222 + count)
                contiguous = RawContentCarver(source).scan(((0, source.size),))
                contiguous_total = source.read_bytes
                contiguous_unique = _unique_read_bytes(source.read_log)
                source.read_log.clear()
                source.read_bytes = 0
                result = PNGIDATFragmentReconstructor(
                    source, volume_start=0, volume_end=source.size,
                    cluster_size=CLUSTER,
                ).reconstruct((0,), ranges)
                reconstructed_unique = _unique_read_bytes(source.read_log)

                self.assertFalse(any(item.extension == ".png" for item in contiguous.files))
                self.assertTrue(any(
                    hashlib.sha256(item.data).hexdigest() == hashlib.sha256(original).hexdigest()
                    for item in result.candidates
                ))
                self.assertEqual(expected_pairs, result.combinations)
                self.assertEqual("search_exhausted", result.stop_reason)
                self.assertLessEqual(result.bytes_read, 32 * 1024 * 1024)
                self.assertEqual(result.bytes_read, source.read_bytes)
                self.assertGreater(result.bytes_read, contiguous_total)
                self.assertLessEqual(contiguous_unique, contiguous_total)
                self.assertLessEqual(reconstructed_unique, result.bytes_read)

    def test_two_valid_decodings_remain_ambiguous(self):
        _, prefix, _ = _parts_png(8, 4, 2, level=3, seed=18)
        alternatives = []
        for seed in (18, 99):
            raw = b"".join(bytes((0,)) + bytes((i + seed) % 256 for i in range(8 * 4))
                            for _row in range(4))
            stream = zlib.compress(raw, 3)
            alternatives.append(stream)
        # The two candidates share the zlib header, then carry different valid
        # compressed tails. Both yield valid PNGs under the same IHDR prefix.
        shared = _chunk(b"IDAT", alternatives[0][:2])
        tails = [_chunk(b"IDAT", item[2:]) for item in alternatives]
        original = prefix + shared + tails[0] + _chunk(b"IEND")
        data = bytearray(b"\xa5" * (8 * CLUSTER))
        data[:len(prefix)] = prefix
        data[CLUSTER:CLUSTER + len(shared)] = shared
        for slot, tail in ((2, tails[0]), (3, tails[1])):
            data[slot * CLUSTER:slot * CLUSTER + len(tail)] = tail
        iend = _chunk(b"IEND")
        for slot in (4, 5):
            data[slot * CLUSTER:slot * CLUSTER + len(iend)] = iend
        source = MemoryDisk(data)
        result = PNGIDATFragmentReconstructor(
            source, volume_start=0, volume_end=len(data), cluster_size=CLUSTER,
        ).reconstruct((0,), ((0, len(data)),))

        self.assertGreaterEqual(len(result.candidates), 2)
        self.assertTrue(all(
            item.evidence["hypothesisStatus"] == "multiple_competing_hypotheses"
            for item in result.candidates
        ))
        self.assertEqual(1, sum(
            hashlib.sha256(item.data).digest() == hashlib.sha256(original).digest()
            for item in result.candidates
        ))
        self.assertEqual("search_exhausted", result.stop_reason)

    def test_missing_and_partially_overwritten_idat_are_rejected(self):
        _, complete = _fixture(foreign=True, seed=73)
        missing = bytearray(complete)
        missing[3 * CLUSTER:4 * CLUSTER] = b"\xa5" * CLUSTER
        overwritten = bytearray(complete)
        overwritten[3 * CLUSTER + 9] ^= 0x01
        for damaged in (bytes(missing), bytes(overwritten)):
            source = MemoryDisk(damaged)
            result = PNGIDATFragmentReconstructor(
                source, volume_start=0, volume_end=len(damaged), cluster_size=CLUSTER,
            ).reconstruct((0,), ((0, len(damaged)),))
            self.assertFalse(result.candidates)
            self.assertEqual("search_exhausted", result.stop_reason)

    def test_complete_chunk_must_remain_inside_its_eligible_range(self):
        original, data = _fixture(foreign=True)
        source = MemoryDisk(data)
        result = PNGIDATFragmentReconstructor(
            source, volume_start=0, volume_end=len(data), cluster_size=CLUSTER,
        ).reconstruct((0,), ((0, 2 * CLUSTER + 8),))

        self.assertFalse(result.candidates)

    def test_prefix_must_remain_inside_its_eligible_range(self):
        _, data = _fixture(foreign=True)
        source = MemoryDisk(data)
        result = PNGIDATFragmentReconstructor(
            source, volume_start=0, volume_end=len(data), cluster_size=CLUSTER,
        ).reconstruct((0,), ((0, 20),))

        self.assertFalse(result.candidates)
        self.assertEqual("search_exhausted", result.stop_reason)
        self.assertEqual(0, result.bytes_read)

    def test_identical_reconstructions_from_duplicate_chunks_are_deduplicated(self):
        original, data = _fixture(foreign=True, seed=91)
        expanded = bytearray(data + b"\xa5" * CLUSTER)
        expanded[5 * CLUSTER:5 * CLUSTER + CLUSTER] = b"\xa5" * CLUSTER
        idat_size = int.from_bytes(expanded[3 * CLUSTER:3 * CLUSTER + 4], "big") + 12
        expanded[5 * CLUSTER:5 * CLUSTER + idat_size] = expanded[
            3 * CLUSTER:3 * CLUSTER + idat_size
        ]
        iend_size = 12
        expanded[6 * CLUSTER:6 * CLUSTER + iend_size] = expanded[
            4 * CLUSTER:4 * CLUSTER + iend_size
        ]
        result = PNGIDATFragmentReconstructor(
            MemoryDisk(expanded), volume_start=0, volume_end=len(expanded),
            cluster_size=CLUSTER,
        ).reconstruct((0,), ((0, len(expanded)),))

        self.assertEqual(1, len(result.candidates))
        self.assertEqual(
            hashlib.sha256(original).digest(),
            hashlib.sha256(result.candidates[0].data).digest(),
        )

    def test_signature_limit_downgrades_earlier_unique_hypothesis(self):
        _, data = _fixture(foreign=True)
        expanded = data + b"\xa5" * (5 * CLUSTER)
        offsets = (0, 7 * CLUSTER, 8 * CLUSTER, 9 * CLUSTER, 10 * CLUSTER)
        result = PNGIDATFragmentReconstructor(
            MemoryDisk(expanded), volume_start=0, volume_end=len(expanded),
            cluster_size=CLUSTER,
        ).reconstruct(offsets, ((0, len(expanded)),))

        self.assertTrue(result.candidates)
        self.assertEqual("signature_limit", result.stop_reason)
        self.assertTrue(all(
            item.evidence["hypothesisStatus"] == "resource_limited_search"
            and not item.evidence["searchComplete"]
            for item in result.candidates
        ))

    def test_contiguous_png_control_remains_in_the_existing_carver(self):
        original, prefix, idats = _parts_png(8, 4, 2, level=6, seed=128)
        contiguous = prefix + b"".join(idats) + _chunk(b"IEND")
        source = MemoryDisk(contiguous)
        result = RawContentCarver(source).scan(((0, len(contiguous)),))

        self.assertEqual(1, len(result.files))
        self.assertEqual(original, result.files[0].data)

    def test_read_failure_and_injected_clock_report_incomplete_search(self):
        _, data = _fixture(foreign=True)

        class FailingDisk(MemoryDisk):
            def read_at(self, offset, size):
                if offset == CLUSTER:
                    raise OSError("synthetic continuation read failure")
                return super().read_at(offset, size)

        failed = PNGIDATFragmentReconstructor(
            FailingDisk(data), volume_start=0, volume_end=len(data), cluster_size=CLUSTER,
        ).reconstruct((0,), ((0, len(data)),))
        self.assertEqual("read_error", failed.stop_reason)
        self.assertFalse(failed.candidates)

        class AdvancingClock:
            def __init__(self):
                self.value = 0.0
            def __call__(self):
                self.value += 0.75
                return self.value

        limited = PNGIDATFragmentReconstructor(
            MemoryDisk(data), volume_start=0, volume_end=len(data), cluster_size=CLUSTER,
            monotonic=AdvancingClock(),
        ).reconstruct((0,), ((0, len(data)),))
        self.assertIn(limited.stop_reason, {"time_limit", "cumulative_time_limit"})
        self.assertFalse(limited.candidates)

    def test_combination_read_and_memory_budgets_are_reported_separately(self):
        data = bytearray(b"\xa5" * (512 * CLUSTER))
        _, prefix, _ = _parts_png(2, 2, 2, level=1, seed=27)
        data[:len(prefix)] = prefix
        source = MemoryDisk(data)
        reconstructor = PNGIDATFragmentReconstructor(
            source, volume_start=0, volume_end=len(data), cluster_size=CLUSTER,
        )
        combo_limited = reconstructor.reconstruct((0,), ((0, len(data)),))
        self.assertEqual("cumulative_combination_limit", combo_limited.stop_reason)
        self.assertEqual(256, combo_limited.combinations)

        with patch.object(PNGIDATFragmentReconstructor, "READS_PER_PASS", 40):
            read_limited = PNGIDATFragmentReconstructor(
                source, volume_start=0, volume_end=len(data), cluster_size=CLUSTER,
            ).reconstruct((0,), ((0, len(data)),))
        self.assertEqual("read_limit", read_limited.stop_reason)
        self.assertLess(read_limited.combinations, 256)
        self.assertGreater(read_limited.bytes_read, 33)

        with patch.object(
            PNGIDATFragmentReconstructor, "TRANSIENT_BUFFER_ESTIMATE", 16 * 1024 * 1024,
        ):
            memory_limited = PNGIDATFragmentReconstructor(
                source, volume_start=0, volume_end=len(data), cluster_size=CLUSTER,
            ).reconstruct((0,), ((0, len(data)),))
        self.assertEqual("memory_limit", memory_limited.stop_reason)
        self.assertEqual(0, memory_limited.combinations)
        self.assertLessEqual(
            memory_limited.retained_bytes_estimate,
            PNGIDATFragmentReconstructor.RETAINED_BYTES,
        )

    def test_original_integrity_is_only_checked_after_catalog_and_extraction(self):
        original, data = _fixture(foreign=True, seed=117)
        opened = []

        def disk_factory(_disk_number):
            disk = MemoryDisk(data)
            opened.append(disk)
            return disk

        volume = NTFSVolume(7, 1, 0, len(data), 512, CLUSTER, 1024, 0, 0, ())
        builder = CatalogBuilder(disk_factory)
        snapshot = builder.build(
            volume,
            include_orphaned=True,
            precomputed_orphans={},
            precomputed_carving_ranges=((0, len(data)),),
            carving_options=CarvingOptionsDto(enable_png_fragment_reconstruction=True),
        )
        hypotheses = [
            node for node in snapshot.catalog.nodes.values()
            if node.candidate and "fragment_reconstruction" in node.candidate.discovery_methods
        ]
        self.assertEqual(1, len(hypotheses))
        node = hypotheses[0]
        self.assertEqual("unknown", node.candidate.integrity_state)
        self.assertIn("Hypothesis", node.name)
        self.assertEqual("fragment_reconstruction", node.candidate.evidence[0].kind)
        self.assertEqual("fragment_structure_hypothesis", node.properties["contentValidation"])
        self.assertEqual(
            node.properties["fragmentReconstruction"],
            CatalogMapper.node(node, {id(node): node.node_id}).to_dict()["fragmentReconstruction"],
        )

        reader = NTFSContentReferenceReader(lambda _source: MemoryDisk(data), builder.content_reference_store)
        extractor = Extractor(
            snapshot.source,
            snapshot.catalog.nodes,
            root_nodes=snapshot.catalog.root_nodes,
            content_reader=reader,
        )
        with tempfile.TemporaryDirectory() as destination:
            recovered = extractor.extract(destination)
            self.assertEqual(1, recovered)
            output = next(path for root, _, names in os.walk(destination)
                          for name in names if (path := os.path.join(root, name)).endswith(".png"))
            with open(output, "rb") as stream:
                extracted = stream.read()

        self.assertEqual(hashlib.sha256(original).hexdigest(), hashlib.sha256(extracted).hexdigest())
        self.assertEqual("search_exhausted", snapshot.content_carving_summary[
            "pngFragmentReconstruction"]["stopReason"])
        self.assertTrue(opened[0].closed)

        incompatible_source = replace(snapshot.source, source_id="changed-synthetic-source")
        incompatible_extractor = Extractor(
            incompatible_source,
            snapshot.catalog.nodes,
            root_nodes=snapshot.catalog.root_nodes,
            content_reader=reader,
        )
        with tempfile.TemporaryDirectory() as destination:
            self.assertEqual(0, incompatible_extractor.extract(destination))
            self.assertEqual("invalid_data", incompatible_extractor.results[0].status)
            self.assertIn("different storage source", incompatible_extractor.results[0].reason)

    def test_disabled_reconstruction_keeps_the_existing_scan_path(self):
        _, data = _fixture(foreign=True, seed=117)
        disk = MemoryDisk(data)
        volume = NTFSVolume(8, 1, 0, len(data), 512, CLUSTER, 1024, 0, 0, ())
        snapshot = CatalogBuilder(lambda _number: disk).build(
            volume,
            include_orphaned=True,
            precomputed_orphans={},
            precomputed_carving_ranges=((0, len(data)),),
            carving_options=CarvingOptionsDto(),
        )

        self.assertNotIn(
            "pngFragmentReconstruction",
            snapshot.content_carving_summary,
        )
        self.assertEqual(0, sum(
            "fragment_reconstruction" in node.candidate.discovery_methods
            for node in snapshot.catalog.nodes.values() if node.candidate
        ))
        self.assertGreater(disk.read_bytes, 0)

    def test_opt_in_defaults_off_and_rejects_non_boolean_values(self):
        self.assertFalse(CarvingOptionsDto.from_payload({}).enable_png_fragment_reconstruction)
        with self.assertRaises(ValueError):
            CarvingOptionsDto.from_payload({"enablePngFragmentReconstruction": 1})


if __name__ == "__main__":
    unittest.main()
