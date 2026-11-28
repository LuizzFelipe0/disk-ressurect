"""Isolated, synthetic-only PNG continuation experiment.

The prefix bytes and its cut position are supplied by each fixture. This file
tests bounded identification of a second-fragment start; it does not discover
the first-fragment boundary and is not connected to production recovery.

The retained-memory counter is a conservative byte-buffer estimate for the
prefix, candidate parsing buffers, validator output, and retained hypotheses.
It excludes Python object overhead, zlib internals, allocator fragmentation,
and the immutable synthetic source fixture; it is not process RSS.
"""

from dataclasses import dataclass
import hashlib
import os
import struct
import sys
import time
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from infrastructure.carving.content_carver import RawContentCarver
from infrastructure.formats.primary import valid_jpeg


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DEFAULT_PAIR_LIMIT = 64
DEFAULT_READ_LIMIT = 8 * 1024 * 1024
DEFAULT_CANDIDATE_LIMIT = 2 * 1024 * 1024
DEFAULT_TIME_LIMIT_SECONDS = 2.0
DEFAULT_RETAINED_MEMORY_LIMIT = 16 * 1024 * 1024
SIMULATED_READ_CHUNK_BYTES = 8
SIMULATED_CANDIDATE_ALIGNMENT = 64


@dataclass(frozen=True)
class ExperimentLimits:
    max_candidate_pairs: int = DEFAULT_PAIR_LIMIT
    max_bytes_read: int = DEFAULT_READ_LIMIT
    max_candidate_bytes: int = DEFAULT_CANDIDATE_LIMIT
    max_seconds: float = DEFAULT_TIME_LIMIT_SECONDS
    max_retained_bytes: int = DEFAULT_RETAINED_MEMORY_LIMIT


@dataclass(frozen=True)
class StructuralHypothesis:
    continuation_offset: int
    data: bytes


@dataclass(frozen=True)
class ExperimentResult:
    hypotheses: tuple[StructuralHypothesis, ...]
    candidate_pairs_attempted: int
    bytes_read: int
    peak_accounted_memory_bytes: int
    read_chunk_boundaries_crossed: int
    elapsed_seconds: float
    stop_reason: str
    error: str | None = None

    @property
    def classification(self):
        if self.stop_reason == "ambiguous":
            return "ambiguous"
        if self.stop_reason == "search_exhausted":
            return "structural_hypothesis" if self.hypotheses else "rejected"
        if self.stop_reason == "error":
            return "error"
        return "limit_reached"


class _ExperimentStop(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class _ReadAccounting:
    """Account logical bytes read and inject a monotonic clock for limits."""

    def __init__(self, limits, monotonic):
        self.limits = limits
        self.monotonic = monotonic
        self.started_at = monotonic()
        self.bytes_read = 0
        self.chunk_boundaries_crossed = 0

    def check_time(self):
        if self.monotonic() - self.started_at >= self.limits.max_seconds:
            raise _ExperimentStop("time_limit")

    @property
    def elapsed(self):
        return max(0.0, self.monotonic() - self.started_at)

    def record_read(self, size):
        self.check_time()
        if self.bytes_read + size > self.limits.max_bytes_read:
            raise _ExperimentStop("bytes_read_limit")
        self.bytes_read += size
        self.check_time()

    def record_chunk_crossings(self, offset, size, chunk_bytes):
        if size:
            first_chunk = offset // chunk_bytes
            last_chunk = (offset + size - 1) // chunk_bytes
            self.chunk_boundaries_crossed += max(0, last_chunk - first_chunk)


class _MemoryReader:
    """Exact positional reads over fixture bytes, split at simulated blocks."""

    def __init__(self, data, accounting, chunk_bytes=SIMULATED_READ_CHUNK_BYTES):
        self._data = bytes(data)
        self._accounting = accounting
        self._chunk_bytes = max(1, int(chunk_bytes))

    def bind_accounting(self, accounting):
        self._accounting = accounting

    @property
    def size(self):
        return len(self._data)

    def read_at(self, offset, size):
        if offset < 0 or size < 0:
            raise OSError("Synthetic read has a negative offset or size")
        end = min(offset + size, len(self._data))
        if offset >= len(self._data) or size == 0:
            return b""

        self._accounting.record_chunk_crossings(offset, min(size, end - offset), self._chunk_bytes)

        pieces = []
        cursor = offset
        while cursor < end:
            boundary = ((cursor // self._chunk_bytes) + 1) * self._chunk_bytes
            next_cursor = min(end, boundary)
            piece = self._data[cursor:next_cursor]
            self._accounting.record_read(len(piece))
            pieces.append(piece)
            cursor = next_cursor
        return b"".join(pieces)


class _FragmentReader:
    """Read the supplied prefix followed by a candidate source range."""

    def __init__(self, prefix, source, start, end, accounting):
        self._prefix = prefix
        self._source = source
        self._start = start
        self._end = end
        self._accounting = accounting
        self.size = len(prefix) + end - start

    def read_at(self, offset, size):
        if offset < 0 or size < 0 or offset + size > self.size:
            raise OSError("Synthetic candidate read escaped its supplied range")
        prefix_length = len(self._prefix)
        if offset >= prefix_length:
            return self._source.read_at(
                self._start + offset - prefix_length, size,
            )

        prefix_end = min(offset + size, prefix_length)
        prefix_piece = self._prefix[offset:prefix_end]
        if prefix_piece:
            self._accounting.record_read(len(prefix_piece))
            self._accounting.record_chunk_crossings(
                offset, len(prefix_piece), SIMULATED_READ_CHUNK_BYTES,
            )
        suffix_size = offset + size - prefix_end
        if suffix_size:
            suffix_piece = self._source.read_at(self._start, suffix_size)
            return prefix_piece + suffix_piece
        return prefix_piece


class PNGFragmentExperiment:
    """Try bounded candidate continuation starts using the existing PNG carver."""

    def __init__(self, *, prefix, source, candidate_ranges, alignment=1,
                 limits=None, monotonic=time.monotonic):
        self.prefix = bytes(prefix)
        self.source = source
        self.candidate_ranges = tuple(candidate_ranges)
        self.alignment = int(alignment)
        self.limits = limits or ExperimentLimits()
        self.monotonic = monotonic

    def run(self):
        accounting = _ReadAccounting(self.limits, self.monotonic)
        hypotheses = []
        attempted = 0
        retained_output_bytes = 0
        peak_memory = len(self.prefix)

        bind_accounting = getattr(self.source, "bind_accounting", None)
        if callable(bind_accounting):
            bind_accounting(accounting)

        try:
            if self.alignment <= 0:
                raise ValueError("Candidate alignment must be positive")
            if len(self.prefix) >= self.limits.max_candidate_bytes:
                raise _ExperimentStop("candidate_size_limit")

            for start, end in self.candidate_ranges:
                if start < 0 or end <= start or end > self.source.size:
                    raise ValueError("Candidate range is outside the synthetic source")
                cursor = ((start + self.alignment - 1) // self.alignment) * self.alignment
                while cursor < end:
                    accounting.check_time()
                    if attempted >= self.limits.max_candidate_pairs:
                        raise _ExperimentStop("candidate_pair_limit")

                    candidate_range_end = self.source.size
                    candidate_size_limit = min(
                        self.limits.max_candidate_bytes - len(self.prefix),
                        candidate_range_end - cursor,
                    )
                    if candidate_size_limit <= 0:
                        cursor += self.alignment
                        continue
                    # Estimate byte buffers only: prefix, parser candidate,
                    # returned candidate, temporary chunk buffers, and retained
                    # output. Python objects and zlib internals are excluded.
                    projected_memory = (
                        len(self.prefix) + 4 * (len(self.prefix) + candidate_size_limit)
                        + retained_output_bytes
                    )
                    peak_memory = max(peak_memory, projected_memory)
                    if projected_memory > self.limits.max_retained_bytes:
                        raise _ExperimentStop("retained_memory_limit")

                    attempted += 1
                    validation_reader = _FragmentReader(
                        self.prefix, self.source, cursor, candidate_range_end,
                        accounting,
                    )
                    carver = RawContentCarver(
                        validation_reader,
                        max_file_bytes=self.limits.max_candidate_bytes,
                        max_candidate_read_bytes=self.limits.max_bytes_read,
                        max_candidate_read_bytes_per_format=self.limits.max_bytes_read,
                        max_decoded_png_bytes=self.limits.max_candidate_bytes,
                    )
                    candidate, _validator_bytes_read, limit_reason = carver._read_png(
                        0,
                        validation_reader.size,
                        self.limits.max_bytes_read - accounting.bytes_read,
                    )
                    accounting.check_time()
                    if limit_reason == "candidate_budget":
                        raise _ExperimentStop("bytes_read_limit")
                    if limit_reason in ("file_size", "decoded_data"):
                        raise _ExperimentStop("candidate_size_limit")

                    if candidate is not None and not any(
                            existing.data == candidate for existing in hypotheses):
                        hypotheses.append(StructuralHypothesis(cursor, candidate))
                        retained_output_bytes += len(candidate)
                        if retained_output_bytes + len(self.prefix) > self.limits.max_retained_bytes:
                            raise _ExperimentStop("retained_memory_limit")
                        if len(hypotheses) > 1:
                            return self._result(
                                hypotheses, attempted, accounting, peak_memory, "ambiguous",
                            )

                    cursor += self.alignment

            return self._result(
                hypotheses, attempted, accounting, peak_memory, "search_exhausted",
            )
        except _ExperimentStop as exc:
            return self._result(
                hypotheses, attempted, accounting, peak_memory, exc.reason,
            )
        except Exception as exc:  # the experiment reports reader/parser errors explicitly
            return self._result(
                hypotheses, attempted, accounting, peak_memory, "error",
                f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _result(hypotheses, attempted, accounting, peak_memory, stop_reason, error=None):
        return ExperimentResult(
            hypotheses=tuple(hypotheses),
            candidate_pairs_attempted=attempted,
            bytes_read=accounting.bytes_read,
            peak_accounted_memory_bytes=peak_memory,
            read_chunk_boundaries_crossed=accounting.chunk_boundaries_crossed,
            elapsed_seconds=accounting.elapsed,
            stop_reason=stop_reason,
            error=error,
        )


def _png_chunk(kind, payload):
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", checksum))


def _png(scanline=b"\x00\x11\x22\x33\xff"):
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    return (PNG_SIGNATURE + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(scanline))
            + _png_chunk(b"IEND", b""))


def _png_prefix_between_chunks(data):
    return len(PNG_SIGNATURE) + 25


def _png_prefix_inside_idat(data):
    idat_start = data.index(b"IDAT") - 4
    compressed_length = int.from_bytes(data[idat_start:idat_start + 4], "big")
    payload_start = idat_start + 8
    return payload_start + 2, payload_start, compressed_length


def _png_with_bad_adler(data):
    mutated = bytearray(data)
    idat_start = mutated.index(b"IDAT") - 4
    payload_length = int.from_bytes(mutated[idat_start:idat_start + 4], "big")
    payload_start = idat_start + 8
    mutated[payload_start + payload_length - 1] ^= 0x01
    checksum_offset = payload_start + payload_length
    checksum = zlib.crc32(
        b"IDAT" + bytes(mutated[payload_start:checksum_offset]),
    ) & 0xFFFFFFFF
    mutated[checksum_offset:checksum_offset + 4] = struct.pack(">I", checksum)
    return bytes(mutated)


def _jpeg(payload=b"deterministic-scan-data"):
    return (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x04\x00\x00"
        + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        + payload.replace(b"\xff", b"\xff\x00")
        + b"\xff\xd9"
    )


def _candidate_region(tails, foreign=b"\x91\x83\x77\x62"):
    """Return candidate bytes plus test-only truth offsets, each 64-byte aligned."""
    region = bytearray()
    offsets = []
    for index, tail in enumerate(tails):
        if index:
            gap_size = SIMULATED_CANDIDATE_ALIGNMENT - (
                len(region) % SIMULATED_CANDIDATE_ALIGNMENT
            )
            region.extend((foreign * ((gap_size + len(foreign) - 1) // len(foreign)))[:gap_size])
        if len(region) % SIMULATED_CANDIDATE_ALIGNMENT:
            padding = SIMULATED_CANDIDATE_ALIGNMENT - (
                len(region) % SIMULATED_CANDIDATE_ALIGNMENT
            )
            region.extend(b"\xa5" * padding)
        offsets.append(len(region))
        region.extend(tail)
    return bytes(region), tuple(offsets)


def _validate_png_contiguous(data, *, chunk_bytes=SIMULATED_READ_CHUNK_BYTES):
    limits = ExperimentLimits(max_candidate_bytes=max(1, len(data)))
    accounting = _ReadAccounting(limits, time.monotonic)
    reader = _MemoryReader(data, accounting, chunk_bytes=chunk_bytes)
    carver = RawContentCarver(
        reader,
        max_file_bytes=max(1, len(data)),
        max_decoded_png_bytes=max(1, len(data)),
    )
    candidate, _bytes_read, _limit = carver._read_png(0, len(data), len(data) * 2)
    return candidate


def _run_fixture(prefix, source_bytes, *, limits=None,
                 monotonic=time.monotonic):
    source = _MemoryReader(
        source_bytes,
        _ReadAccounting(limits or ExperimentLimits(), monotonic),
    )
    # Use one accounting ledger for source reads and validation rereads.
    experiment = PNGFragmentExperiment(
        prefix=prefix,
        source=source,
        candidate_ranges=((0, len(source_bytes)),),
        alignment=SIMULATED_CANDIDATE_ALIGNMENT,
        limits=limits,
        monotonic=monotonic,
    )
    return experiment.run()


IMAGE_FIXTURE_MATRIX = {
    "JPEG": {
        "extensions": (".jpg", ".jpeg"),
        "prototype_strategy": None,
        "fragment_cut_kind": "inside entropy-coded scan payload",
        "fixture_cases": ("contiguous control", "two fragments separated by foreign bytes"),
    },
    "PNG": {
        "extensions": (".png",),
        "prototype_strategy": "bounded continuation-start search with supplied prefix/cut",
        "fragment_cut_kinds": ("between chunks", "inside IDAT payload"),
    },
}


class _FakeClock:
    def __init__(self, tick_seconds=0.0):
        self.value = 0.0
        self.tick_seconds = tick_seconds

    def __call__(self):
        value = self.value
        self.value += self.tick_seconds
        return value


class PNGFragmentExperimentTests(unittest.TestCase):
    def test_matrix_has_jpeg_controls_and_fragment_fixture_but_no_jpeg_strategy(self):
        original = _jpeg()
        cut = original.index(b"deterministic") + 5
        first_fragment, second_fragment = original[:cut], original[cut:]
        foreign = b"FOREIGN"
        fragmented_fixture = first_fragment + foreign + second_fragment

        self.assertEqual(IMAGE_FIXTURE_MATRIX["JPEG"]["extensions"], (".jpg", ".jpeg"))
        self.assertIsNone(IMAGE_FIXTURE_MATRIX["JPEG"]["prototype_strategy"])
        self.assertTrue(valid_jpeg(original))
        self.assertTrue(valid_jpeg(first_fragment + second_fragment))
        self.assertGreater(len(first_fragment), 0)
        self.assertGreater(len(second_fragment), 0)
        self.assertIn(foreign, fragmented_fixture)
        self.assertEqual(fragmented_fixture[:cut], first_fragment)

    def test_contiguous_png_control_is_structurally_accepted(self):
        image = _png()

        self.assertEqual(IMAGE_FIXTURE_MATRIX["PNG"]["extensions"], (".png",))
        self.assertEqual(_validate_png_contiguous(image), image)

    def test_png_signature_can_cross_a_synthetic_read_boundary(self):
        image = _png()
        limits = ExperimentLimits(max_candidate_bytes=len(image))
        accounting = _ReadAccounting(limits, time.monotonic)
        reader = _MemoryReader(image, accounting, chunk_bytes=5)
        carver = RawContentCarver(
            reader,
            max_file_bytes=len(image),
            max_decoded_png_bytes=len(image),
        )

        candidate, _bytes_read, _limit = carver._read_png(0, len(image), len(image) * 2)

        self.assertEqual(candidate, image)
        self.assertGreater(accounting.chunk_boundaries_crossed, 0)

    def test_finds_continuation_after_supplied_cut_between_chunks(self):
        original = _png()
        cut = _png_prefix_between_chunks(original)
        prefix = original[:cut]
        correct_tail = original[cut:]
        wrong_tail = _png_with_bad_adler(_png(b"\x00\x44"))[cut:]
        self.assertEqual(_png(b"\x00\x44")[:cut], prefix)
        candidate_bytes, oracle_offsets = _candidate_region((wrong_tail, correct_tail))

        result = _run_fixture(prefix, candidate_bytes)
        # The oracle offset and original digest are consulted only after search.
        matching = [
            hypothesis for hypothesis in result.hypotheses
            if hashlib.sha256(hypothesis.data).digest() == hashlib.sha256(original).digest()
        ]

        self.assertEqual(result.stop_reason, "search_exhausted")
        self.assertEqual(result.classification, "structural_hypothesis")
        self.assertEqual(len(result.hypotheses), 1)
        self.assertEqual(matching[0].continuation_offset, oracle_offsets[1])
        self.assertGreater(result.read_chunk_boundaries_crossed, 0)

    def test_finds_continuation_after_supplied_cut_inside_idat(self):
        original = _png()
        cut, _payload_start, _payload_length = _png_prefix_inside_idat(original)
        prefix = original[:cut]
        correct_tail = original[cut:]
        overwritten_tail = _png_with_bad_adler(original)[cut:]
        candidate_bytes, oracle_offsets = _candidate_region((overwritten_tail, correct_tail))

        result = _run_fixture(prefix, candidate_bytes)
        matching = [
            hypothesis for hypothesis in result.hypotheses
            if hashlib.sha256(hypothesis.data).digest() == hashlib.sha256(original).digest()
        ]

        self.assertEqual(result.stop_reason, "search_exhausted")
        self.assertEqual(result.classification, "structural_hypothesis")
        self.assertEqual(len(result.hypotheses), 1)
        self.assertEqual(matching[0].continuation_offset, oracle_offsets[1])

    def test_returns_ambiguous_for_two_structurally_valid_idat_continuations(self):
        original = _png(b"\x00\x11\x22\x33\xff")
        alternate = _png(b"\x00\xaa\xbb\xcc\xdd")
        cut, _payload_start, original_idat_length = _png_prefix_inside_idat(original)
        alternate_cut, _alternate_payload_start, alternate_idat_length = (
            _png_prefix_inside_idat(alternate)
        )
        self.assertEqual(cut, alternate_cut)
        self.assertEqual(original_idat_length, alternate_idat_length)
        self.assertEqual(original[:cut], alternate[:cut])
        prefix = original[:cut]

        false_tail = _png_with_bad_adler(alternate)[cut:]
        candidate_bytes, oracle_offsets = _candidate_region(
            (false_tail, original[cut:], alternate[cut:]),
        )
        result = _run_fixture(prefix, candidate_bytes)

        # Hashes are post-search test oracles. They cannot help the experiment
        # choose between two candidates that pass the same available checks.
        matches_original = [
            hypothesis for hypothesis in result.hypotheses
            if hashlib.sha256(hypothesis.data).digest() == hashlib.sha256(original).digest()
        ]
        self.assertEqual(result.stop_reason, "ambiguous")
        self.assertEqual(result.classification, "ambiguous")
        self.assertEqual(len(result.hypotheses), 2)
        self.assertEqual(len(matches_original), 1)
        self.assertIn(matches_original[0].continuation_offset, oracle_offsets[1:])

    def test_missing_fragment_and_partial_overwrite_are_rejected(self):
        original = _png()
        cut, _payload_start, _payload_length = _png_prefix_inside_idat(original)
        prefix = original[:cut]

        for name, candidate_tail in (
            ("missing", b"\x91\x83\x77\x62" * 3),
            ("overwritten", _png_with_bad_adler(original)[cut:]),
        ):
            with self.subTest(name=name):
                candidate_bytes, _oracle_offsets = _candidate_region((candidate_tail,))
                result = _run_fixture(prefix, candidate_bytes)
                self.assertEqual(result.stop_reason, "search_exhausted")
                self.assertEqual(result.classification, "rejected")
                self.assertEqual(result.hypotheses, ())

    def test_pair_limit_does_not_promote_one_unfinished_hypothesis_to_unique(self):
        original = _png()
        cut = _png_prefix_between_chunks(original)
        prefix = original[:cut]
        alternative = _png(b"\x00\xaa\xbb\xcc\xdd")
        self.assertEqual(alternative[:cut], prefix)
        candidate_bytes, _oracle_offsets = _candidate_region(
            (original[cut:], alternative[cut:]),
        )

        result = _run_fixture(
            prefix,
            candidate_bytes,
            limits=ExperimentLimits(max_candidate_pairs=1),
        )

        self.assertEqual(result.stop_reason, "candidate_pair_limit")
        self.assertEqual(result.classification, "limit_reached")
        self.assertEqual(len(result.hypotheses), 1)

    def test_reports_independent_read_memory_and_time_limits(self):
        original = _png()
        cut = _png_prefix_between_chunks(original)
        prefix = original[:cut]
        candidate_bytes = original[cut:]

        cases = (
            ("bytes_read_limit", ExperimentLimits(max_bytes_read=8), time.monotonic),
            ("retained_memory_limit", ExperimentLimits(max_retained_bytes=1), time.monotonic),
            ("time_limit", ExperimentLimits(max_seconds=0.01), _FakeClock(0.005)),
        )
        for expected_reason, limits, clock in cases:
            with self.subTest(limit=expected_reason):
                result = _run_fixture(prefix, candidate_bytes, limits=limits, monotonic=clock)
                self.assertEqual(result.stop_reason, expected_reason)
                self.assertEqual(result.classification, "limit_reached")

    def test_reports_synthetic_reader_errors(self):
        class FailingReader(_MemoryReader):
            def read_at(self, _offset, _size):
                raise OSError("synthetic reader failure")

        limits = ExperimentLimits()
        accounting = _ReadAccounting(limits, time.monotonic)
        reader = FailingReader(b"x" * 64, accounting)
        result = PNGFragmentExperiment(
            prefix=_png()[:_png_prefix_between_chunks(_png())],
            source=reader,
            candidate_ranges=((0, reader.size),),
            alignment=2,
            limits=limits,
        ).run()

        self.assertEqual(result.stop_reason, "error")
        self.assertIn("synthetic reader failure", result.error)


if __name__ == "__main__":
    unittest.main()
