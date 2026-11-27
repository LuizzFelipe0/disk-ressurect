"""Create a clearly labeled PNG crop from recovered original pixel rows."""

from __future__ import annotations

from dataclasses import dataclass
import json
import struct
import zlib

from modules.catalog.entities import PngPartialRecovery
from modules.recovery.entities import ExtractionResult
from infrastructure.filesystems.recovery_output_writer import (
    RecoveryOutputWriter,
    UnsafeRecoveryPath,
)


@dataclass(frozen=True)
class _OutputRecord:
    name: str
    full_path: str


class PngPartialExporter:
    def __init__(self, output_writer: RecoveryOutputWriter | None = None):
        self.output_writer = output_writer or RecoveryOutputWriter()

    def export(self, recovery: PngPartialRecovery, output_directory: str) -> ExtractionResult:
        filename = f"Partial_PNG_{recovery.recovery_id[:16]}.png"
        record = _OutputRecord(filename, filename)
        temporary_path = None
        created_directories = ()
        published = False
        bytes_written = 0
        try:
            destination, temporary_template, created_directories = (
                self.output_writer.prepare_target(output_directory, filename)
            )
            data = self._encode_crop(recovery)
            output, temporary_path = self.output_writer.open_temporary(temporary_template)
            with output:
                self.output_writer.write_chunk(output, data)
                bytes_written = len(data)
            self.output_writer.publish(temporary_path, destination)
            published = True
            record = _OutputRecord(filename, destination)
            return ExtractionResult(
                record,
                "partial_exported",
                "Derived PNG crop contains only decoded source rows; original file integrity is unknown",
                bytes_written,
            )
        except OSError as exc:
            return ExtractionResult(record, "io_error", str(exc), bytes_written)
        except UnsafeRecoveryPath as exc:
            return ExtractionResult(record, "invalid_path", str(exc), bytes_written)
        except (ValueError, TypeError, OverflowError) as exc:
            return ExtractionResult(record, "invalid_data", str(exc), bytes_written)
        finally:
            self.output_writer.discard(temporary_path)
            if not published:
                self.output_writer.cleanup_empty_directories(created_directories)

    @staticmethod
    def _encode_crop(recovery: PngPartialRecovery) -> bytes:
        color_type = 2 if recovery.channels == 3 else 6
        height = recovery.recovered_row_count
        ihdr = struct.pack(
            ">IIBBBBB", recovery.width, height, 8, color_type, 0, 0, 0,
        )
        metadata = {
            "artifactType": "derived_partial_recovery_export",
            "originalFormat": "PNG",
            "originalPixelLayout": recovery.pixel_layout,
            "originalDimensions": {"width": recovery.width, "height": recovery.height},
            "decodedOriginalRows": {"start": 0, "endExclusive": height},
            "unavailableOriginalRows": {
                "start": height, "endExclusive": recovery.height,
            } if height < recovery.height else None,
            "sourceId": recovery.source_id,
            "volumeId": recovery.volume_id,
            "sourceRanges": [
                {"start": start, "endExclusive": end}
                for start, end in recovery.source_ranges
            ],
            "validationEvidence": {
                "validIdatCrcCount": recovery.valid_idat_crc_count,
                "idatCrcUnknown": recovery.idat_crc_unknown,
                "idatCrcInvalid": recovery.idat_crc_invalid,
                "zlibComplete": recovery.zlib_complete,
                "iendValid": recovery.iend_valid,
                "stopReason": recovery.stop_reason,
                "integrity": "unknown",
            },
            "generatedStructures": ["cropped IHDR", "filter-zero scanlines", "IDAT", "IEND", "iTXt provenance"],
        }
        pixel_stream = bytearray()
        for row in recovery.rows:
            pixel_stream.append(0)
            pixel_stream.extend(row)
        compressed = zlib.compress(bytes(pixel_stream), level=6)
        chunks = [
            PngPartialExporter._chunk(b"IHDR", ihdr),
            PngPartialExporter._chunk(
                b"iTXt", b"Disk-Ressurect\x00\x00\x00\x00\x00"
                + json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            ),
            PngPartialExporter._chunk(b"IDAT", compressed),
            PngPartialExporter._chunk(b"IEND", b""),
        ]
        return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)

    @staticmethod
    def _chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))
