"""Production PNG partial-row scanning and derived export tests."""

from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zlib

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from infrastructure.carving.content_carver import RawContentCarver
from infrastructure.carving.png_partial_recovery import PngPartialRecoveryScanner
from infrastructure.formats.png_partial_decoder import decode_png_partial_rows
from infrastructure.recovery.png_partial_exporter import PngPartialExporter
from modules.catalog.entities import RecoveryCatalog, RecoveryCatalogSnapshot
from modules.recovery.dto import RecoveryRequestDto
from modules.recovery.service import RecoveryWorkflow
from modules.storage.entities import StorageSource


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class MemorySource:
    def __init__(self, data):
        self.data = bytes(data)
        self.size = len(self.data)

    def read_at(self, offset, size):
        return self.data[offset:offset + size]


class OutputGuard:
    def validate_source(self, output_directory, source):
        self.call = (output_directory, source.source_id)


def _png_with_partial_idat():
    width, height = 48, 20
    pixels = bytes((index * 37 + index // 7) & 0xFF for index in range(width * height * 3))
    image = Image.frombytes("RGB", (width, height), pixels)
    buffer = BytesIO()
    image.save(buffer, format="PNG", compress_level=1)
    complete = buffer.getvalue()
    cursor = len(PNG_SIGNATURE)
    while cursor + 12 <= len(complete):
        length = int.from_bytes(complete[cursor:cursor + 4], "big")
        kind = complete[cursor + 4:cursor + 8]
        payload_start = cursor + 8
        if kind == b"IDAT":
            # Supply a fixed prefix boundary to the scanner; only the test oracle
            # knows the original continuation and source pixels.
            payload_prefix = max(16, length * 3 // 4)
            cut = payload_start + min(payload_prefix, length)
            return complete[:cut], complete, pixels, (payload_start, cut)
        cursor += length + 12
    raise AssertionError("Pillow PNG fixture has no IDAT chunk")


class PngPartialRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.truncated_png, self.original_png, self.original_pixels, self.payload_range = (
            _png_with_partial_idat()
        )

    def _scan(self):
        offset = 128
        eligible_bytes = self.truncated_png + b"\xA5" * 1024
        source = MemorySource(b"foreign-bytes" * 9 + bytes(offset - 117)
                              + eligible_bytes)
        end = offset + len(eligible_bytes)
        scan = PngPartialRecoveryScanner(
            source, source_id="synthetic-source", volume_id="synthetic-volume",
            volume_start=0, volume_end=source.size,
        ).scan((offset,), ((offset, end),))
        return source, offset, scan

    def test_decoder_yields_only_complete_rows_and_absolute_source_ranges(self):
        result = decode_png_partial_rows(
            self.truncated_png, source_offset=0x5000,
        )

        self.assertEqual(result.status, "partial")
        self.assertGreater(len(result.rows), 0)
        self.assertLess(len(result.rows), result.height)
        self.assertEqual(result.source_ranges[0][0], 0x5000 + self.payload_range[0])
        self.assertEqual(result.source_ranges[0][1], 0x5000 + self.payload_range[1])
        self.assertTrue(result.idat_crc_unknown)
        self.assertFalse(result.zlib_complete)

    def test_scan_is_bounded_to_the_supplied_eligible_range(self):
        source, offset, result = self._scan()

        self.assertEqual(len(result.recoveries), 1)
        self.assertEqual(result.signatures_examined, 1)
        self.assertEqual(result.stop_reason, "search_exhausted")
        self.assertEqual(result.bytes_read, len(self.truncated_png) + 1024)
        self.assertEqual(result.unique_bytes_read, len(self.truncated_png) + 1024)
        self.assertEqual(result.recoveries[0].source_id, "synthetic-source")
        self.assertEqual(result.recoveries[0].source_ranges[0][0],
                         offset + self.payload_range[0])
        self.assertLessEqual(result.retained_bytes_estimate,
                             PngPartialRecoveryScanner.MAX_TOTAL_RETAINED_BYTES)

    def test_contiguous_carver_rejects_candidate_that_partial_scan_exports_as_crop(self):
        source, offset, scan = self._scan()
        carver = RawContentCarver(source, chunk_size=512, max_scan_bytes=4096)
        contiguous = carver.scan(((offset, offset + len(self.truncated_png)),),
                                 collect_png_signatures=True)

        self.assertFalse(contiguous.files)
        self.assertEqual(len(scan.recoveries), 1)

    def test_workflow_exports_a_cropped_png_with_explicit_missing_rows_and_provenance(self):
        _, _, scan = self._scan()
        partial = scan.recoveries[0]
        source = StorageSource("synthetic-source", "raw_image", "synthetic", 4096, 512, "memory")
        snapshot = RecoveryCatalogSnapshot(
            RecoveryCatalog({}), source=source, source_id=source.source_id,
            volume_id="synthetic-volume",
            partial_png_recoveries=scan.recoveries,
        )
        output_guard = OutputGuard()
        workflow = RecoveryWorkflow(
            output_guard, lambda _source: None, object(),
            lambda *_args, **_kwargs: EmptyExtractor(),
            partial_png_exporter=PngPartialExporter(),
        )
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with tempfile.TemporaryDirectory(dir=repo_root) as output_directory:
            summary = workflow.extract_selection(
                snapshot, [], output_directory, (), selected_partial_png_ids=(partial.recovery_id,),
            )
            result = summary.results[0]
            output_path = Path(result.path)
            with Image.open(output_path) as exported:
                self.assertEqual(exported.size, (partial.width, partial.recovered_row_count))
                self.assertEqual(exported.mode, "RGB")
                self.assertEqual(exported.tobytes(), self.original_pixels[:
                    partial.recovered_row_count * partial.width * 3])
            metadata = _read_itxt(output_path.read_bytes())

        self.assertEqual(summary.recovered_count, 0)
        self.assertEqual(summary.partial_exported_count, 1)
        self.assertEqual(result.status, "partial_exported")
        self.assertIn("integrity is unknown", result.reason)
        self.assertEqual(metadata["artifactType"], "derived_partial_recovery_export")
        self.assertEqual(metadata["validationEvidence"]["integrity"], "unknown")
        self.assertEqual(metadata["unavailableOriginalRows"]["start"], partial.recovered_row_count)
        self.assertEqual(output_guard.call, (output_directory, source.source_id))

    def test_workflow_rejects_partial_id_from_a_different_catalog(self):
        source = StorageSource("synthetic-source", "raw_image", "synthetic", 4096, 512, "memory")
        workflow = RecoveryWorkflow(OutputGuard(), lambda _source: None, object(),
                                    lambda *_args, **_kwargs: EmptyExtractor(),
                                    partial_png_exporter=PngPartialExporter())
        snapshot = RecoveryCatalogSnapshot(RecoveryCatalog({}), source=source)
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as output_directory:
            with self.assertRaisesRegex(ValueError, "not in the current catalog"):
                workflow.extract_selection(
                    snapshot, [], output_directory, (), selected_partial_png_ids=("stale",),
                )

    def test_workflow_rejects_partial_id_from_a_different_volume(self):
        _, _, scan = self._scan()
        source = StorageSource("synthetic-source", "raw_image", "synthetic", 4096, 512, "memory")
        snapshot = RecoveryCatalogSnapshot(
            RecoveryCatalog({}), source=source, source_id=source.source_id,
            volume_id="another-volume", partial_png_recoveries=scan.recoveries,
        )
        workflow = RecoveryWorkflow(OutputGuard(), lambda _source: None, object(),
                                    lambda *_args, **_kwargs: EmptyExtractor(),
                                    partial_png_exporter=PngPartialExporter())
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as output_directory:
            with self.assertRaisesRegex(ValueError, "different volume"):
                workflow.extract_selection(
                    snapshot, [], output_directory, (),
                    selected_partial_png_ids=(scan.recoveries[0].recovery_id,),
                )

    def test_request_dto_accepts_separate_partial_png_selection(self):
        request = RecoveryRequestDto.from_payload({
            "selectedNodeIds": [], "selectedPartialPngIds": ["partial-id"],
            "excludedNodeIds": [], "extensions": [], "outputDirectory": "C:/synthetic",
        })

        self.assertEqual(request.selected_partial_png_ids, ("partial-id",))


class EmptyExtractor:
    def __init__(self):
        self.results = []

    def set_filters(self, *_args):
        pass

    def extract(self, *_args, **_kwargs):
        return 0


def _read_itxt(data):
    cursor = len(PNG_SIGNATURE)
    while cursor + 12 <= len(data):
        length = int.from_bytes(data[cursor:cursor + 4], "big")
        kind = data[cursor + 4:cursor + 8]
        payload = data[cursor + 8:cursor + 8 + length]
        if kind == b"iTXt":
            keyword, text = payload.split(b"\x00", 1)
            compression_flag, compression_method, rest = text[0], text[1], text[2:]
            language, rest = rest.split(b"\x00", 1)
            translated, text = rest.split(b"\x00", 1)
            if compression_flag == 1:
                text = zlib.decompress(text)
            return json.loads(text.decode("utf-8"))
        cursor += length + 12
    raise AssertionError("PNG iTXt provenance chunk not found")


if __name__ == "__main__":
    unittest.main()
