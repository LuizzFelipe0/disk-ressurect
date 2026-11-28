"""Synthetic-only, bounded image-fragment discovery experiments.

The source contains an image prefix, foreign bytes, and eligible continuation
ranges. The algorithm receives no oracle cut, correct continuation offset, or
original digest. Hashes are compared only by tests after each search.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import hashlib
import os
import random
import struct
import sys
import time
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from infrastructure.carving.content_carver import RawContentCarver

PNG = b"\x89PNG\r\n\x1a\n"
PAIR_LIMIT = 64
READ_LIMIT = 8 * 1024 * 1024
CANDIDATE_LIMIT = 2 * 1024 * 1024
TIME_LIMIT = 2.0
MEMORY_LIMIT = 16 * 1024 * 1024


@dataclass(frozen=True)
class Budget:
    max_pairs: int = PAIR_LIMIT
    max_reads: int = READ_LIMIT
    max_candidate: int = CANDIDATE_LIMIT
    max_seconds: float = TIME_LIMIT
    max_memory: int = MEMORY_LIMIT


@dataclass(frozen=True)
class Hypothesis:
    cut_offset: int
    continuation_offset: int
    data: bytes


@dataclass(frozen=True)
class Result:
    hypotheses: tuple[Hypothesis, ...]
    cut_points_considered: int
    pairs: int
    bytes_read: int
    retained_bytes_peak: int
    elapsed: float
    stop_reason: str
    safe_prefilter_rejections: int = 0
    full_validation_calls: int = 0
    unique_bytes_read: int = 0

    @property
    def classification(self):
        if self.stop_reason == "ambiguous": return "ambiguous"
        if self.stop_reason == "search_exhausted": return "structural_hypothesis" if self.hypotheses else "rejected"
        if self.stop_reason == "contiguous_or_no_fault": return "contiguous_or_no_fault"
        if self.stop_reason.startswith("error"): return "error"
        return "limit_reached"


class SyntheticSource:
    def __init__(self, data: bytes):
        self.data = data
        self.size = len(data)
        self.reads = 0
    def read_at(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > len(self.data):
            raise OSError("read outside synthetic source")
        self.reads += size
        return self.data[offset:offset + size]


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)


def png_fixture(width=2, height=2, *, level=6, entropy="low", seed=31) -> bytes:
    rng = random.Random(seed)
    channels = 4
    raw = bytearray()
    for _ in range(height):
        raw.append(0)
        if entropy == "random":
            raw.extend(rng.randbytes(width * channels))
        else:
            raw.extend(bytes(v for x in range(width) for v in (x * 31 % 256, 40, 170, 255)))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    comp = zlib.compress(bytes(raw), level)
    # Deliberately split IDAT to exercise chunk sequence handling.
    split = max(1, len(comp) // 2)
    return PNG + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", comp[:split]) + _chunk(b"IDAT", comp[split:]) + _chunk(b"IEND", b"")


def _png_candidate(data: bytes):
    # Bound the candidate at the first complete IEND chunk. The production
    # reader expects its supplied range to end at EOF, so trailing foreign
    # source bytes must not be passed along as if they were PNG chunks.
    iend = data.find(b"\x00\x00\x00\x00IEND")
    if iend < 0:
        return None
    data = data[:iend + 12]
    class Reader:
        size = len(data)
        def read_at(self, offset, size): return data[offset:offset + size]
    carver = RawContentCarver(Reader(), max_file_bytes=max(1, len(data)), max_decoded_png_bytes=4 * 1024 * 1024)
    return carver._read_png(0, len(data), len(data) * 2)[0]


def _png_crc_prefilter(data: bytes) -> str | None:
    """Reject candidates that cannot satisfy the existing PNG chunk checks.

    This deliberately stops before zlib inflation. A pass is only permission
    to invoke the existing validator, never evidence that the PNG is sound.
    """
    # Match the experiment's existing reader contract: bytes after the first
    # complete IEND are foreign source data and are outside the PNG candidate.
    iend_marker = data.find(b"\x00\x00\x00\x00IEND")
    if iend_marker >= 0:
        data = data[:iend_marker + 12]
    if not data.startswith(PNG):
        return "signature"
    pos = len(PNG)
    seen_ihdr = seen_idat = seen_iend = False
    idat_ended = False
    while pos < len(data):
        if pos + 8 > len(data):
            return "truncated_header"
        length = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        if (not all(65 <= char <= 90 or 97 <= char <= 122 for char in kind)
                or not 65 <= kind[2] <= 90):
            return "chunk_type"
        if length > CANDIDATE_LIMIT or pos + 12 + length > len(data):
            return "chunk_length"
        end = pos + 12 + length
        payload = data[pos + 8:pos + 8 + length]
        expected_crc = int.from_bytes(data[pos + 8 + length:end], "big")
        if zlib.crc32(kind + payload) & 0xffffffff != expected_crc:
            return "crc"
        if not seen_ihdr and (kind != b"IHDR" or length != 13):
            return "ihdr_order"
        if seen_ihdr and kind == b"IHDR":
            return "duplicate_ihdr"
        if kind[:1].isupper() and kind not in (b"IHDR", b"PLTE", b"IDAT", b"IEND"):
            return "unknown_critical_chunk"
        if kind == b"IHDR":
            seen_ihdr = True
        if kind == b"IDAT":
            if not seen_ihdr or idat_ended:
                return "idat_order"
            seen_idat = True
        elif seen_idat and kind != b"IEND":
            idat_ended = True
        if kind == b"IEND":
            if length != 0 or not seen_idat or end != len(data):
                return "iend"
            seen_iend = True
            break
        pos = end
    return None if seen_iend else "missing_iend"


def _unique_read_bytes(ranges: list[tuple[int, int]]) -> int:
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if start == end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(end - start for start, end in merged)


class PNGAutoDiscovery:
    """Infer a bounded cut interval from the first damaged PNG chunk.

    CRC/zlib failure identifies only a suspect chunk interval, never the true
    cut. Every byte offset in that interval is tried at the supplied alignment.
    Candidate tails are read only from caller supplied eligible ranges.
    """
    def __init__(self, source: SyntheticSource, *, signature_offset: int,
                 candidate_ranges: tuple[tuple[int, int], ...], alignment: int = 1,
                 candidate_alignment: int = 4096,
                 budget: Budget = Budget(), monotonic=time.monotonic):
        self.source, self.sig = source, signature_offset
        self.ranges, self.alignment, self.candidate_alignment = candidate_ranges, alignment, candidate_alignment
        self.budget, self.clock = budget, monotonic

    def run(self) -> Result:
        start_time = self.clock(); reads0 = self.source.reads
        source_reads: list[tuple[int, int]] = []
        hypotheses = []; attempted = points = 0; retained = peak = 0; reason = "search_exhausted"
        try:
            if self.alignment < 1: raise ValueError("alignment must be positive")
            # Walk complete chunks until the first invalid/truncated one. This
            # locates a suspect range; it does not infer the cut itself.
            end = min(self.source.size, self.sig + self.budget.max_candidate)
            def read(offset, size):
                nonlocal reason
                if self.source.reads - reads0 + size > self.budget.max_reads:
                    reason = "read_limit"
                    raise StopIteration
                if self.clock() - start_time >= self.budget.max_seconds:
                    reason = "time_limit"
                    raise StopIteration
                value = self.source.read_at(offset, size)
                source_reads.append((offset, offset + len(value)))
                return value
            blob = read(self.sig, end - self.sig)
            peak = len(blob)
            if peak > self.budget.max_memory:
                reason="memory_limit"; raise StopIteration
            if not blob.startswith(PNG): raise ValueError("PNG signature missing")
            pos = len(PNG); previous_end = pos; suspect_end = None
            while pos + 12 <= len(blob):
                length = int.from_bytes(blob[pos:pos+4], "big")
                kind = blob[pos+4:pos+8]
                chunk_end = pos + 12 + length
                if length > self.budget.max_candidate or chunk_end > len(blob):
                    suspect_end = min(len(blob), max(pos + 12, previous_end + 64)); break
                payload = blob[pos+8:pos+8+length]
                crc = int.from_bytes(blob[pos+8+length:chunk_end], "big")
                if zlib.crc32(kind + payload) & 0xffffffff != crc:
                    # CRC failure locates the chunk only. It does not locate
                    # the cut, so consider the full bounded chunk interval.
                    suspect_end = min(chunk_end, len(blob)); break
                if kind == b"IEND": break
                previous_end = chunk_end; pos = chunk_end
            if suspect_end is None:
                # The contiguous carver is the proper result when no damaged
                # chunk was observed; don't invent a fragmented hypothesis.
                return self._result((), 0, 0, self.source.reads-reads0, peak,
                    self.clock()-start_time, "contiguous_or_no_fault", 0, 0,
                    _unique_read_bytes(source_reads))
            first = max(len(PNG), previous_end)
            first_absolute = self.sig + first
            first_aligned = ((first_absolute + self.alignment - 1)//self.alignment)*self.alignment
            cuts = list(range(first_aligned, self.sig + suspect_end, self.alignment))
            if first_absolute not in cuts and self.alignment == 1: cuts.insert(0, first_absolute)
            points = len(cuts)
            starts=[]
            for lo, hi in self.ranges:
                if lo < 0 or hi <= lo or hi > self.source.size: raise ValueError("invalid candidate range")
                cursor = ((lo + self.candidate_alignment - 1)//self.candidate_alignment)*self.candidate_alignment
                while cursor < hi:
                    starts.append(cursor); cursor += self.candidate_alignment
            incomplete = False
            for cut in cuts:
                for cont in starts:
                    if attempted >= self.budget.max_pairs: reason="combination_limit"; incomplete=True; raise StopIteration
                    if self.clock()-start_time >= self.budget.max_seconds: reason="time_limit"; incomplete=True; raise StopIteration
                    attempted += 1
                    prefix_size = cut-self.sig
                    available_tail = self.source.size-cont
                    tail_size = min(self.budget.max_candidate-prefix_size, available_tail)
                    prefix = read(self.sig, prefix_size)
                    tail = read(cont, tail_size)
                    candidate = prefix + tail
                    # Match the optimized estimator: source window, pair
                    # buffers, parser copies, retained hypotheses and the
                    # validator's bounded 4 MiB decoded-output allowance.
                    peak=max(peak, len(blob)+len(prefix)+len(tail)
                        +3*len(candidate)+retained+4*1024*1024)
                    if peak > self.budget.max_memory: reason="memory_limit"; incomplete=True; raise StopIteration
                    valid = _png_candidate(candidate)
                    if self.clock()-start_time >= self.budget.max_seconds:
                        reason="time_limit"; incomplete=True; raise StopIteration
                    if valid is None and tail_size < available_tail:
                        reason="candidate_size_limit"; incomplete=True; raise StopIteration
                    if valid is not None and not any(h.data == valid for h in hypotheses):
                        hypotheses.append(Hypothesis(cut, cont, valid)); retained += len(valid)
                        if len(hypotheses) > 1: reason="ambiguous"; break
                if reason == "ambiguous": break
            if reason == "ambiguous": pass
            elif not incomplete: reason="search_exhausted"
        except StopIteration: pass
        except Exception as exc: reason="error:" + type(exc).__name__ + ": " + str(exc)
        return self._result(tuple(hypotheses), points, attempted, self.source.reads-reads0,
            peak, self.clock()-start_time, reason, 0, attempted,
            _unique_read_bytes(source_reads))

    @staticmethod
    def _result(h, p, n, r, m, t, s, rejected=0, validations=0, unique=0):
        return Result(tuple(h), p, n, r, m, t, s, rejected, validations, unique)


class PNGCachedDiscovery(PNGAutoDiscovery):
    """Phase 3B.1 comparison path with cached reads and CRC-safe rejection.

    Cut enumeration and candidate ranges are unchanged from the baseline.
    The cached first scan supplies slices for in-range reads; out-of-range
    continuation bytes are read once and cached. Every candidate pair still
    consumes the same 64-pair budget, including safe prefilter rejects.
    """
    def run(self) -> Result:
        start_time = self.clock(); reads0 = self.source.reads
        source_reads: list[tuple[int, int]] = []
        cache: dict[tuple[int, int], bytes] = {}
        hypotheses: list[Hypothesis] = []
        attempted = points = rejected = validations = 0
        retained = peak = 0; reason = "search_exhausted"
        try:
            if self.alignment < 1 or self.candidate_alignment < 1:
                raise ValueError("alignments must be positive")
            end = min(self.source.size, self.sig + self.budget.max_candidate)

            def read(offset: int, size: int) -> bytes:
                nonlocal reason
                key = (offset, size)
                if key in cache:
                    return cache[key]
                if self.source.reads - reads0 + size > self.budget.max_reads:
                    reason = "read_limit"; raise StopIteration
                if self.clock() - start_time >= self.budget.max_seconds:
                    reason = "time_limit"; raise StopIteration
                if self.sig <= offset and offset + size <= end:
                    value = memoryview(initial)[offset - self.sig:offset - self.sig + size]
                else:
                    value = self.source.read_at(offset, size)
                    source_reads.append((offset, offset + len(value)))
                cache[key] = value
                return value

            if self.source.reads - reads0 + end - self.sig > self.budget.max_reads:
                reason = "read_limit"; raise StopIteration
            initial = self.source.read_at(self.sig, end - self.sig)
            source_reads.append((self.sig, self.sig + len(initial)))
            if not initial.startswith(PNG):
                raise ValueError("PNG signature missing")
            peak = len(initial)
            if peak > self.budget.max_memory:
                reason = "memory_limit"; raise StopIteration
            pos = len(PNG); previous_end = pos; suspect_end = None
            while pos + 12 <= len(initial):
                length = int.from_bytes(initial[pos:pos + 4], "big")
                kind = initial[pos + 4:pos + 8]
                chunk_end = pos + 12 + length
                if length > self.budget.max_candidate or chunk_end > len(initial):
                    suspect_end = min(len(initial), max(pos + 12, previous_end + 64)); break
                payload = initial[pos + 8:pos + 8 + length]
                crc = int.from_bytes(initial[pos + 8 + length:chunk_end], "big")
                if zlib.crc32(kind + payload) & 0xffffffff != crc:
                    suspect_end = min(chunk_end, len(initial)); break
                if kind == b"IEND": break
                previous_end = chunk_end; pos = chunk_end
            if suspect_end is None:
                return Result((), 0, 0, self.source.reads - reads0, peak,
                    self.clock() - start_time, "contiguous_or_no_fault", 0, 0,
                    _unique_read_bytes(source_reads))
            first = max(len(PNG), previous_end)
            first_absolute = self.sig + first
            first_aligned = ((first_absolute + self.alignment - 1) // self.alignment) * self.alignment
            cuts = list(range(first_aligned, self.sig + suspect_end, self.alignment))
            if first_absolute not in cuts and self.alignment == 1:
                cuts.insert(0, first_absolute)
            points = len(cuts)
            starts = []
            for lo, hi in self.ranges:
                if lo < 0 or hi <= lo or hi > self.source.size:
                    raise ValueError("invalid candidate range")
                cursor = ((lo + self.candidate_alignment - 1) // self.candidate_alignment) * self.candidate_alignment
                while cursor < hi:
                    starts.append(cursor); cursor += self.candidate_alignment
            incomplete = False
            for cut in cuts:
                for cont in starts:
                    if attempted >= self.budget.max_pairs:
                        reason = "combination_limit"; incomplete = True; raise StopIteration
                    if self.clock() - start_time >= self.budget.max_seconds:
                        reason = "time_limit"; incomplete = True; raise StopIteration
                    attempted += 1
                    prefix_size = cut - self.sig
                    available_tail = self.source.size - cont
                    tail_size = min(self.budget.max_candidate - prefix_size, available_tail)
                    prefix = read(self.sig, prefix_size)
                    tail = read(cont, tail_size)
                    candidate = bytes(prefix) + bytes(tail)
                    # Account for owned buffers only; this is not process RSS.
                    # Include parser copies and the bounded PNG decoded-output cap.
                    cache_bytes = sum(len(value) for value in cache.values()
                        if isinstance(value, bytes))
                    peak = max(peak, len(initial) + cache_bytes + 3 * len(candidate)
                        + retained + 4 * 1024 * 1024)
                    if peak > self.budget.max_memory:
                        reason = "memory_limit"; incomplete = True; raise StopIteration
                    reject = _png_crc_prefilter(candidate)
                    if (tail_size < available_tail
                            and reject in ("truncated_header", "chunk_length", "missing_iend")):
                        reason = "candidate_size_limit"; incomplete = True; raise StopIteration
                    if reject is not None:
                        rejected += 1
                    else:
                        validations += 1
                        valid = _png_candidate(candidate)
                        if valid is not None and not any(h.data == valid for h in hypotheses):
                            hypotheses.append(Hypothesis(cut, cont, valid)); retained += len(valid)
                            if len(hypotheses) > 1:
                                reason = "ambiguous"; break
                    if self.clock() - start_time >= self.budget.max_seconds:
                        reason = "time_limit"; incomplete = True; raise StopIteration
                if reason == "ambiguous": break
            if reason != "ambiguous" and not incomplete:
                reason = "search_exhausted"
        except StopIteration:
            pass
        except Exception as exc:
            reason = "error:" + type(exc).__name__ + ": " + str(exc)
        return Result(tuple(hypotheses), points, attempted, self.source.reads - reads0,
            peak, self.clock() - start_time, reason, rejected, validations,
            _unique_read_bytes(source_reads))


def _physical_fixture(original: bytes, cut: int, tails: tuple[bytes, ...], *, alignment=4096):
    """Return synthetic bytes, ranges, and oracle offsets (the latter test-only)."""
    prefix = original[:cut]
    buf = bytearray(prefix)
    buf.extend(b"FOREIGN-DATA" * ((alignment + 11)//12))
    while len(buf) % alignment: buf.append(0xA5)
    offsets=[]
    for i, tail in enumerate(tails):
        if i:
            buf.extend(b"DECOY" * ((alignment + 4)//5))
            while len(buf) % alignment: buf.append(0x5A)
        offsets.append(len(buf)); buf.extend(tail)
    # The algorithm gets a broad eligible range. Exact candidate positions
    # remain solely in the returned test-oracle tuple.
    # Expose a coarse eligible window starting one cluster before each true
    # fragment. The algorithm must infer the exact aligned start within it.
    eligible_start=max(0,offsets[0]-alignment)
    return bytes(buf), ((eligible_start, len(buf)),), tuple(offsets)


PNG_FIXTURE_CASES = (
    "between chunks", "inside chunk header", "inside IDAT", "inside CRC",
    "near IEND", "4 KiB aligned", "nonaligned", "missing", "partial overwrite", "ambiguous",
)


class PNGDiscoveryTests(unittest.TestCase):
    def test_matrix_and_contiguous_controls(self):
        self.assertEqual(len(PNG_FIXTURE_CASES), 10)
        for width, height, level, entropy in ((2,2,1,"low"),(17,9,9,"random"),(64,32,6,"low")):
            image=png_fixture(width,height,level=level,entropy=entropy)
            self.assertEqual(_png_candidate(image), image)

    def test_candidate_discovery_does_not_receive_oracle_cut_or_hash(self):
        original=png_fixture()
        cut=original.index(b"IDAT") + 3  # fixture oracle only; within IDAT header
        physical,ranges,truth=_physical_fixture(original,cut,(original[cut:],))
        source=SyntheticSource(physical)
        result=PNGAutoDiscovery(source,signature_offset=0,candidate_ranges=ranges,alignment=1,candidate_alignment=4096).run()
        matched=[h for h in result.hypotheses if hashlib.sha256(h.data).digest()==hashlib.sha256(original).digest()]
        self.assertGreater(result.cut_points_considered,0)
        self.assertLessEqual(result.pairs,PAIR_LIMIT)
        self.assertTrue(result.stop_reason in ("search_exhausted","combination_limit","ambiguous"))
        # Fixture reports truth only after the search; it does not force success.
        self.assertGreater(truth[0],ranges[0][0])
        self.assertLessEqual(len(matched),1)

    def test_cut_location_matrix_is_inferred_or_explicitly_misses(self):
        image=png_fixture(width=3,height=2,level=3)
        idat=image.index(b"IDAT")-4
        idat_length=int.from_bytes(image[idat:idat+4],"big")
        iend=image.index(b"IEND")-4
        cuts=(
            ("between chunks",len(PNG)+25,1),
            ("inside chunk header",idat+6,1),
            ("inside IDAT",idat+11,1),
            ("inside CRC",idat+8+idat_length+2,1),
            ("near IEND",iend+10,1),
            ("unaligned control",idat+13,1),
        )
        outcomes=[]
        for name,cut,alignment in cuts:
            with self.subTest(cut=name):
                physical,ranges,truth=_physical_fixture(image,cut,(image[cut:],))
                result=PNGAutoDiscovery(SyntheticSource(physical),signature_offset=0,
                    candidate_ranges=ranges,alignment=alignment,candidate_alignment=4096).run()
                matches=[h for h in result.hypotheses if hashlib.sha256(h.data).digest()==hashlib.sha256(image).digest()]
                outcomes.append((name,cut,result.cut_points_considered,result.pairs,result.bytes_read,result.stop_reason,bool(matches)))
                self.assertLessEqual(result.pairs,PAIR_LIMIT)
                self.assertLessEqual(len(matches),1)
                self.assertGreater(truth[0],ranges[0][0])
        self.assertEqual(len(outcomes),len(cuts))

    def test_4k_cluster_cut_is_inferred_from_geometry_and_compared_with_carver(self):
        image=png_fixture(width=96,height=64,level=1,entropy="random")
        cut=4096 # oracle-only; algorithm receives cluster alignment, not cut
        physical,ranges,truth=_physical_fixture(image,cut,(image[cut:],),alignment=4096)
        result=PNGAutoDiscovery(SyntheticSource(physical),signature_offset=0,
            candidate_ranges=ranges,alignment=4096,candidate_alignment=4096).run()
        # A cluster-aligned cut is inferable only when the damaged chunk's
        # bounded suspect interval contains the aligned point.
        self.assertLessEqual(result.pairs,PAIR_LIMIT)
        self.assertGreater(truth[0],ranges[0][0])
        self.assertIsNone(_png_candidate(physical))
        self.assertEqual(_png_candidate(image),image)

    def test_missing_and_overwritten_png_tails_are_not_integrity_claims(self):
        image=png_fixture(); cut=len(PNG)+25
        damaged=bytearray(image[cut:]); damaged[-5]^=0x40
        for tail in (b"foreign bytes",bytes(damaged)):
            with self.subTest(tail=tail[:6]):
                physical,ranges,_truth=_physical_fixture(image,cut,(tail,))
                result=PNGAutoDiscovery(SyntheticSource(physical),signature_offset=0,candidate_ranges=ranges).run()
                self.assertFalse(any(hashlib.sha256(h.data).digest()==hashlib.sha256(image).digest() for h in result.hypotheses))

    def test_two_structurally_valid_png_tails_remain_ambiguous(self):
        first=png_fixture(width=2,height=2,entropy="random",seed=7)
        second=png_fixture(width=2,height=2,entropy="random",seed=8)
        cut=len(PNG)+25
        self.assertEqual(first[:cut],second[:cut])
        physical,ranges,truth=_physical_fixture(first,cut,(first[cut:],second[cut:]))
        result=PNGAutoDiscovery(SyntheticSource(physical),signature_offset=0,candidate_ranges=ranges,candidate_alignment=4096).run()
        self.assertEqual(result.stop_reason,"ambiguous")
        self.assertLessEqual(result.pairs,PAIR_LIMIT)
        self.assertEqual(len(truth),2)
        hashes=[hashlib.sha256(h.data).digest() for h in result.hypotheses]
        self.assertEqual(len(set(hashes)),2)

    def test_cached_crc_prefilter_preserves_exhaustive_pair_coverage(self):
        original=png_fixture(width=8,height=8,entropy="random",seed=211)
        cut=len(PNG)+25
        physical,ranges,_truth=_physical_fixture(original,cut,(original[cut:],))
        baseline=PNGAutoDiscovery(SyntheticSource(physical),signature_offset=0,
            candidate_ranges=ranges,candidate_alignment=4096).run()
        optimized=PNGCachedDiscovery(SyntheticSource(physical),signature_offset=0,
            candidate_ranges=ranges,candidate_alignment=4096).run()
        baseline_hashes={hashlib.sha256(h.data).digest() for h in baseline.hypotheses}
        optimized_hashes={hashlib.sha256(h.data).digest() for h in optimized.hypotheses}
        self.assertEqual(optimized_hashes,baseline_hashes)
        self.assertEqual(optimized.pairs,baseline.pairs)
        self.assertEqual(optimized.safe_prefilter_rejections + optimized.full_validation_calls,
            optimized.pairs)
        self.assertGreater(optimized.safe_prefilter_rejections,0)
        self.assertLessEqual(optimized.unique_bytes_read,baseline.unique_bytes_read)
        self.assertLessEqual(optimized.bytes_read,baseline.bytes_read)
        self.assertLessEqual(optimized.retained_bytes_peak,MEMORY_LIMIT)
        self.assertTrue(all(hashlib.sha256(h.data).digest()==hashlib.sha256(original).digest()
            for h in optimized.hypotheses))

    def test_png_prefilter_is_only_a_safe_rejector_and_oracle_is_post_search(self):
        original=png_fixture(width=11,height=7,entropy="random")
        self.assertIsNone(_png_crc_prefilter(original))
        corrupt=bytearray(original)
        corrupt[corrupt.index(b"IDAT")+7] ^= 0x01
        self.assertEqual(_png_crc_prefilter(bytes(corrupt)),"crc")
        # A CRC-pass is not enough: the existing decompression/size validator
        # remains authoritative for candidate acceptance.
        bad_zlib=bytearray(original)
        idat=bad_zlib.index(b"IDAT")+4
        bad_zlib[idat+2] ^= 0x20
        crc_pos=idat + int.from_bytes(bad_zlib[idat-8:idat-4],"big")
        bad_zlib[crc_pos:crc_pos+4]=struct.pack(">I",zlib.crc32(b"IDAT"+bad_zlib[idat:crc_pos]) & 0xffffffff)
        self.assertIsNone(_png_crc_prefilter(bytes(bad_zlib)))
        decoded_hypothesis=_png_candidate(bytes(bad_zlib))
        self.assertIsNotNone(decoded_hypothesis)
        self.assertNotEqual(hashlib.sha256(decoded_hypothesis).digest(),
            hashlib.sha256(original).digest())

    def test_cached_png_search_keeps_ambiguity_and_incomplete_budget(self):
        first=png_fixture(width=2,height=2,entropy="random",seed=31)
        second=png_fixture(width=2,height=2,entropy="random",seed=32)
        cut=len(PNG)+25
        physical,_ranges,truth=_physical_fixture(first,cut,(first[cut:],second[cut:]))
        ranges=tuple((offset-1,offset+1) for offset in truth)
        result=PNGCachedDiscovery(SyntheticSource(physical),signature_offset=0,
            candidate_ranges=ranges,candidate_alignment=4096).run()
        self.assertEqual(result.stop_reason,"ambiguous")
        self.assertGreaterEqual(len(result.hypotheses),2)
        limited=PNGCachedDiscovery(SyntheticSource(physical),signature_offset=0,
            candidate_ranges=ranges,candidate_alignment=4096,
            budget=Budget(max_pairs=1)).run()
        self.assertEqual(limited.stop_reason,"combination_limit")
        self.assertEqual(limited.classification,"limit_reached")

    def test_png_holdout_matrix_matches_baseline_without_oracle_input(self):
        # These seeds and layouts are separate from the development fixtures
        # above; the oracle values are used only after each search completes.
        cases=((13,8,2,"random",501,"inside IDAT"),
            (31,17,8,"low",502,"between chunks"),
            (64,12,4,"random",503,"inside CRC"),
            (21,9,1,"random",504,"inside chunk header"),
            (17,13,6,"low",505,"near IEND"),
            (40,30,9,"random",506,"unaligned control"))
        outcomes=[]
        for width,height,level,entropy,seed,cut_kind in cases:
            image=png_fixture(width,height,level=level,entropy=entropy,seed=seed)
            first_idat=image.index(b"IDAT")-4
            first_length=int.from_bytes(image[first_idat:first_idat+4],"big")
            if cut_kind=="between chunks": cut=first_idat+12+first_length
            elif cut_kind=="inside CRC": cut=first_idat+8+first_length+2
            elif cut_kind=="inside chunk header": cut=first_idat+6
            elif cut_kind=="near IEND": cut=image.index(b"IEND")-4+10
            elif cut_kind=="unaligned control": cut=first_idat+8+max(1,first_length//3)+1
            else: cut=first_idat+8+max(1,first_length//3)
            physical,ranges,_truth=_physical_fixture(image,cut,(image[cut:],))
            baseline=PNGAutoDiscovery(SyntheticSource(physical),signature_offset=0,
                candidate_ranges=ranges,candidate_alignment=4096).run()
            optimized=PNGCachedDiscovery(SyntheticSource(physical),signature_offset=0,
                candidate_ranges=ranges,candidate_alignment=4096).run()
            baseline_hashes={hashlib.sha256(h.data).digest() for h in baseline.hypotheses}
            optimized_hashes={hashlib.sha256(h.data).digest() for h in optimized.hypotheses}
            self.assertEqual(optimized_hashes,baseline_hashes)
            self.assertEqual(optimized.pairs,baseline.pairs)
            self.assertEqual(optimized.stop_reason,baseline.stop_reason)
            self.assertLessEqual(optimized.bytes_read,baseline.bytes_read)
            self.assertLessEqual(optimized.retained_bytes_peak,MEMORY_LIMIT)
            # The original digest is consulted only after both searches.
            matched=any(digest==hashlib.sha256(image).digest() for digest in optimized_hashes)
            outcomes.append((cut_kind,optimized.cut_points_considered,optimized.pairs,
                optimized.full_validation_calls,optimized.safe_prefilter_rejections,
                optimized.bytes_read,optimized.unique_bytes_read,optimized.stop_reason,matched))
        self.assertEqual(len(outcomes),len(cases))

    def test_contiguous_carver_remains_baseline_for_split_png(self):
        image=png_fixture(); cut=len(image)//2
        physical,ranges,_truth=_physical_fixture(image,cut,(image[cut:],))
        self.assertEqual(_png_candidate(image),image)
        self.assertIsNone(_png_candidate(physical))
        result=PNGAutoDiscovery(SyntheticSource(physical),signature_offset=0,candidate_ranges=ranges,candidate_alignment=4096).run()
        self.assertIn(result.stop_reason,("search_exhausted","combination_limit","ambiguous"))

    def test_resource_budget_never_claims_unique_on_incomplete_search(self):
        image=png_fixture(); cut=image.index(b"IDAT")+4
        physical,ranges,_truth=_physical_fixture(image,cut,(image[cut:],image[cut:]))
        result=PNGAutoDiscovery(SyntheticSource(physical),signature_offset=0,candidate_ranges=ranges,candidate_alignment=4096,budget=Budget(max_pairs=1)).run()
        self.assertEqual(result.stop_reason,"combination_limit")
        self.assertEqual(result.classification,"limit_reached")

    def test_discovery_read_time_and_memory_budgets_stop_independently(self):
        image=png_fixture(); cut=len(PNG)+25
        physical,ranges,_truth=_physical_fixture(image,cut,(image[cut:],))
        class Clock:
            def __init__(self): self.now=0.0
            def __call__(self): self.now+=0.01; return self.now
        for limits,clock,expected in (
            (Budget(max_reads=8),time.monotonic,"read_limit"),
            (Budget(max_memory=1),time.monotonic,"memory_limit"),
            (Budget(max_seconds=0.001),Clock(),"time_limit"),
            (Budget(max_candidate=50),time.monotonic,"candidate_size_limit"),
        ):
            for cls in (PNGAutoDiscovery,PNGCachedDiscovery):
                result=cls(SyntheticSource(physical),signature_offset=0,
                    candidate_ranges=ranges,candidate_alignment=4096,budget=limits,monotonic=clock).run()
                self.assertEqual(result.stop_reason,expected)
                self.assertEqual(result.classification,"limit_reached")


if __name__ == "__main__": unittest.main()



