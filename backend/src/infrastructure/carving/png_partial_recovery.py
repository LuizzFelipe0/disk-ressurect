"""Opt-in bounded discovery of partial PNG pixel rows in trusted ranges."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time

from infrastructure.formats.png_partial_decoder import (
    MAX_INPUT_BYTES,
    MAX_RETAINED_BYTES,
    PngPartialDecode,
    decode_png_partial_rows,
)
from modules.catalog.entities import PngPartialRecovery


@dataclass(frozen=True)
class PngPartialRecoveryScan:
    recoveries: tuple[PngPartialRecovery, ...]
    signatures_seen: int
    signatures_examined: int
    bytes_read: int
    unique_bytes_read: int
    elapsed_seconds: float
    retained_bytes_estimate: int
    rejected_count: int
    read_errors: int
    stop_reason: str


class PngPartialRecoveryScanner:
    MAX_SIGNATURES = 4
    MAX_CANDIDATE_READ_BYTES = MAX_INPUT_BYTES
    MAX_TOTAL_READ_BYTES = 8 * 1024 * 1024
    MAX_TOTAL_RETAINED_BYTES = MAX_RETAINED_BYTES
    TIME_LIMIT_SECONDS = 2.0

    def __init__(self, source, *, source_id, volume_id, volume_start, volume_end,
                 monotonic=time.monotonic):
        self.source = source
        self.source_id = str(source_id)
        self.volume_id = str(volume_id)
        self.volume_start = int(volume_start)
        self.volume_end = int(volume_end)
        self.clock = monotonic
        if (not self.source_id or not self.volume_id or self.volume_start < 0
                or self.volume_end <= self.volume_start):
            raise ValueError("PNG partial recovery source and volume bounds are invalid")

    def scan(self, signature_offsets, eligible_ranges, *, complete_png_offsets=()):
        started = self.clock()
        ranges = self._validate_ranges(eligible_ranges)
        signatures = tuple(sorted(set(int(offset) for offset in signature_offsets)))
        complete = {int(offset) for offset in complete_png_offsets}
        if any(offset < self.volume_start or offset >= self.volume_end for offset in signatures):
            raise ValueError("PNG signature is outside the selected volume")

        recoveries = []
        bytes_read = 0
        read_ranges = []
        retained = 0
        retained_peak_estimate = 0
        examined = rejected = read_errors = 0
        stop_reason = "search_exhausted"
        for signature in signatures:
            if signature in complete:
                continue
            if examined >= self.MAX_SIGNATURES:
                stop_reason = "signature_limit"
                break
            if self.clock() - started >= self.TIME_LIMIT_SECONDS:
                stop_reason = "time_limit"
                break
            eligible = next(
                ((start, end) for start, end in ranges if start <= signature < end), None,
            )
            if eligible is None or signature < self.volume_start:
                rejected += 1
                continue
            _, range_end = eligible
            candidate_size = min(
                self.MAX_CANDIDATE_READ_BYTES,
                range_end - signature,
                self.volume_end - signature,
                self.MAX_TOTAL_READ_BYTES - bytes_read,
            )
            if candidate_size < 33:
                stop_reason = "read_limit" if bytes_read >= self.MAX_TOTAL_READ_BYTES else "range_too_small"
                break
            examined += 1
            try:
                candidate = bytes(self.source.read_at(signature, candidate_size))
            except OSError:
                read_errors += 1
                stop_reason = "read_error"
                break
            bytes_read += len(candidate)
            if len(candidate) != candidate_size:
                read_ranges.append((signature, signature + len(candidate)))
                read_errors += 1
                stop_reason = "read_error"
                break
            read_ranges.append((signature, signature + len(candidate)))
            if self.clock() - started >= self.TIME_LIMIT_SECONDS:
                stop_reason = "time_limit"
                break

            decoded: PngPartialDecode = decode_png_partial_rows(
                candidate,
                source_offset=signature,
                max_input_bytes=self.MAX_CANDIDATE_READ_BYTES,
                max_retained_bytes=max(0, self.MAX_TOTAL_RETAINED_BYTES - retained),
                time_limit_seconds=max(0.0, self.TIME_LIMIT_SECONDS - (self.clock() - started)),
                clock=self.clock,
            )
            if decoded.status != "partial" or not decoded.rows:
                rejected += 1
                if decoded.stop_reason in {"retained_memory_limit", "time_limit"}:
                    stop_reason = decoded.stop_reason
                    break
                continue
            packed_rows = b"".join(decoded.rows)
            retained_row_bytes = len(packed_rows)
            retained_peak_estimate = max(
                retained_peak_estimate,
                retained + len(candidate) + 2 * decoded.decoded_bytes
                + 64 * 1024,
            )
            recovery_identity = hashlib.sha256(
                (f"{self.source_id}:{self.volume_id}:{signature}:"
                 f"{decoded.width}:{decoded.height}:{decoded.channels}:").encode("utf-8")
                + packed_rows
            ).hexdigest()
            try:
                recovery = PngPartialRecovery(
                    recovery_id=recovery_identity,
                    source_id=self.source_id,
                    volume_id=self.volume_id,
                    signature_offset=signature,
                    source_ranges=decoded.source_ranges,
                    width=int(decoded.width),
                    height=int(decoded.height),
                    channels=int(decoded.channels),
                    rows=decoded.rows,
                    stop_reason=decoded.stop_reason,
                    valid_idat_crc_count=decoded.valid_idat_crc_count,
                    idat_crc_unknown=decoded.idat_crc_unknown,
                    idat_crc_invalid=decoded.idat_crc_invalid,
                    zlib_complete=decoded.zlib_complete,
                    iend_valid=decoded.iend_valid,
                )
            except ValueError:
                del packed_rows
                rejected += 1
                continue
            del packed_rows
            recoveries.append(recovery)
            retained += retained_row_bytes

        unique_bytes = self._unique_bytes_read(read_ranges)
        return PngPartialRecoveryScan(
            tuple(recoveries), len(signatures), examined, bytes_read, unique_bytes,
            max(0.0, self.clock() - started), max(retained, retained_peak_estimate),
            rejected, read_errors, stop_reason,
        )

    def _validate_ranges(self, eligible_ranges):
        normalized = []
        for start, end in eligible_ranges:
            start, end = int(start), int(end)
            if (start < self.volume_start or end > self.volume_end or end <= start):
                raise ValueError("PNG partial recovery range is outside the volume")
            normalized.append((start, end))
        normalized.sort()
        if any(left[1] > right[0] for left, right in zip(normalized, normalized[1:])):
            raise ValueError("PNG partial recovery ranges overlap")
        return tuple(normalized)

    @staticmethod
    def _unique_bytes_read(intervals):
        intervals = sorted(intervals)
        total = 0
        current_start = current_end = None
        for start, end in intervals:
            if current_end is None or start > current_end:
                if current_end is not None:
                    total += current_end - current_start
                current_start, current_end = start, end
            else:
                current_end = max(current_end, end)
        if current_end is not None:
            total += current_end - current_start
        return total
