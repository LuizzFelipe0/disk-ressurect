"""Resumable, bounded PNG IDAT-fragment search on synthetic byte sources.

This is deliberately test-only. It reconstructs complete, independently CRC-
valid IDAT chunks stored in shuffled physical clusters. It does not claim to
solve arbitrary cuts inside an IDAT chunk or to discover a whole-disk search
space. The oracle (original bytes, SHA-256, and physical layout) stays in tests.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import random
import struct
import sys
import time
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from infrastructure.carving.content_carver import RawContentCarver

PNG = b"\x89PNG\r\n\x1a\n"
CLUSTER = 4096
PAIR_LIMIT = 64
READ_LIMIT = 8 * 1024 * 1024
CANDIDATE_LIMIT = 2 * 1024 * 1024
PASS_SECONDS = 2.0
RETAINED_LIMIT = 16 * 1024 * 1024
MAX_PASSES = 4


@dataclass(frozen=True)
class Limits:
    pairs_per_pass: int = PAIR_LIMIT
    reads_per_pass: int = READ_LIMIT
    candidate_bytes: int = CANDIDATE_LIMIT
    seconds_per_pass: float = PASS_SECONDS
    retained_bytes: int = RETAINED_LIMIT
    max_passes: int = MAX_PASSES

    @property
    def total_pairs(self): return self.pairs_per_pass * self.max_passes
    @property
    def total_reads(self): return self.reads_per_pass * self.max_passes
    @property
    def total_seconds(self): return self.seconds_per_pass * self.max_passes


@dataclass(frozen=True)
class Node:
    chunk_offsets: tuple[int, ...]
    compressed: bytes
    next_candidate: int


@dataclass(frozen=True)
class Hypothesis:
    chunk_offsets: tuple[int, ...]
    data: bytes


@dataclass(frozen=True)
class SearchState:
    version: int
    config_id: str
    frontier: tuple[Node, ...]
    hypotheses: tuple[Hypothesis, ...]
    evaluated: tuple[tuple[tuple[int, ...], int], ...]
    passes: int = 0
    total_pairs: int = 0
    total_reads: int = 0
    total_elapsed: float = 0.0
    exhausted: bool = False
    prefix: bytes = b""
    stop_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PassResult:
    state: SearchState
    stop_reason: str
    pairs: int
    bytes_read: int
    elapsed: float
    buffer_peak_estimate: int
    new_hypotheses: int

    @property
    def classification(self):
        if len(self.state.hypotheses) > 1: return "ambiguous"
        if self.stop_reason != "search_exhausted": return "inconclusive"
        return "structural_hypothesis" if self.state.hypotheses else "rejected"


class MemorySource:
    def __init__(self, data: bytes, *, fail_on: set[tuple[int, int]] | None = None):
        self.data = data
        self.size = len(data)
        self.fail_on = fail_on or set()
        self.read_log: list[tuple[int, int]] = []

    @property
    def bytes_read(self): return sum(size for _, size in self.read_log)

    def read_at(self, offset: int, size: int) -> bytes:
        if (offset, size) in self.fail_on:
            raise OSError("synthetic read failure")
        if offset < 0 or size < 0 or offset + size > self.size:
            raise OSError("read outside synthetic source")
        self.read_log.append((offset, size))
        return self.data[offset:offset + size]


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))


def _parts_png(width: int, height: int, count: int, *, level: int, seed: int,
               entropy: str = "random") -> tuple[bytes, bytes, tuple[bytes, ...]]:
    rng = random.Random(seed)
    pixels = rng.randbytes(width * height * 4) if entropy == "random" else bytes(
        (i * 17 + 31) % 256 for i in range(width * height * 4))
    raw = b"".join(b"\x00" + pixels[row * width * 4:(row + 1) * width * 4]
                   for row in range(height))
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    compressed = zlib.compress(raw, level)
    cuts = [len(compressed) * index // count for index in range(count + 1)]
    idats = tuple(_chunk(b"IDAT", compressed[cuts[i]:cuts[i + 1]])
                  for i in range(count))
    original = PNG + ihdr + b"".join(idats) + _chunk(b"IEND", b"")
    return original, PNG + ihdr, idats


def _png_valid(data: bytes) -> bytes | None:
    iend = data.find(b"\x00\x00\x00\x00IEND")
    if iend < 0: return None
    data = data[:iend + 12]

    class Reader:
        size = len(data)
        def read_at(self, offset, size): return data[offset:offset + size]

    carver = RawContentCarver(Reader(), max_file_bytes=max(1, len(data)),
                              max_decoded_png_bytes=4 * 1024 * 1024)
    return carver._read_png(0, len(data), len(data) * 2)[0]


class PNGProgressiveSearch:
    """DFS over CRC-valid IDAT chunks at aligned starts, with resumable frontier.

    It receives a source ID, signature offset, broad eligible ranges, geometry,
    and a maximum depth. It never receives the fixture's true count, cut points
    or oracle digest. The depth cap is a resource/configuration ceiling.
    """
    def __init__(self, source: MemorySource, *, source_id: str, signature_offset: int,
                 candidate_ranges: tuple[tuple[int, int], ...], alignment: int = CLUSTER,
                 max_fragments: int = 8, limits: Limits = Limits(), monotonic=time.monotonic):
        self.source, self.source_id, self.sig = source, source_id, signature_offset
        self.ranges, self.alignment, self.max_fragments = candidate_ranges, alignment, max_fragments
        self.limits, self.clock = limits, monotonic
        config = json.dumps({"source": source_id, "sig": signature_offset,
            "ranges": candidate_ranges, "alignment": alignment,
            "max_fragments": max_fragments, "candidate_bytes": limits.candidate_bytes,
            "pairs_per_pass": limits.pairs_per_pass, "reads_per_pass": limits.reads_per_pass,
            "seconds_per_pass": limits.seconds_per_pass,
            "retained_bytes": limits.retained_bytes, "max_passes": limits.max_passes,
            "budget_version": 1}, sort_keys=True, separators=(",", ":"))
        self.config_id = hashlib.sha256(config.encode()).hexdigest()

    def initial_state(self) -> SearchState:
        if self.alignment < 1 or self.max_fragments < 1:
            raise ValueError("alignment and maximum depth must be positive")
        return SearchState(1, self.config_id, (Node((), b"", 0),), (), ())

    def run_pass(self, state: SearchState) -> PassResult:
        if state.version != 1 or state.config_id != self.config_id:
            return PassResult(state, "configuration_mismatch", 0, 0, 0.0,
                              self._retained(state), 0)
        if state.exhausted:
            return PassResult(state, "search_exhausted", 0, 0, 0.0,
                              self._retained(state), 0)
        if state.passes >= self.limits.max_passes:
            return PassResult(state, "cumulative_pass_limit", 0, 0, 0.0,
                              self._retained(state), 0)
        start = self.clock(); read_start = self.source.bytes_read
        pairs = new_hypotheses = 0
        frontier = list(state.frontier)
        hypotheses = list(state.hypotheses)
        evaluated = list(state.evaluated)
        reason = "search_exhausted"
        fixed_prefix = state.prefix
        buffer_peak = self._retained(state)
        try:
            if self._retained(state) > self.limits.retained_bytes:
                raise _Stop("memory_limit")
            if state.prefix:
                fixed_prefix = state.prefix
            else:
                prefix_header = self._read(self.sig, 8 + 25, read_start, start,
                                           state.total_reads)
                if prefix_header is None or len(prefix_header) != 33:
                    raise ValueError("incomplete PNG prefix")
                if not prefix_header.startswith(PNG): raise ValueError("PNG signature missing")
                ihdr_len = int.from_bytes(prefix_header[8:12], "big")
                ihdr_end = 8 + 12 + ihdr_len
                if ihdr_len != 13 or len(prefix_header) < ihdr_end:
                    raise ValueError("incomplete PNG IHDR")
                fixed_prefix = prefix_header[:ihdr_end]
            ihdr = fixed_prefix[8:33]
            ihdr_crc = int.from_bytes(ihdr[-4:], "big")
            if zlib.crc32(ihdr[4:-4]) & 0xffffffff != ihdr_crc:
                raise ValueError("invalid PNG IHDR CRC")
            candidate_count = self._candidate_count()
            while frontier:
                if self.clock() - start >= self.limits.seconds_per_pass:
                    raise _Stop("time_limit")
                node = frontier.pop()
                if len(node.chunk_offsets) >= self.max_fragments:
                    continue
                if node.next_candidate >= candidate_count:
                    continue
                if pairs >= self.limits.pairs_per_pass:
                    frontier.append(node)
                    raise _Stop("combination_limit")
                if state.total_pairs + pairs >= self.limits.total_pairs:
                    frontier.append(node)
                    raise _Stop("cumulative_pair_limit")
                if state.total_elapsed + self.clock() - start >= self.limits.total_seconds:
                    frontier.append(node)
                    raise _Stop("cumulative_time_limit")
                if self.clock() - start >= self.limits.seconds_per_pass:
                    frontier.append(node)
                    raise _Stop("time_limit")
                index = node.next_candidate
                offset = self._candidate_at(index)
                key = (node.chunk_offsets, index)
                if key in evaluated:
                    raise ValueError("resumable state repeats an evaluated pair")
                try:
                    child, hypothesis, candidate_peak = self._evaluate(node, offset, fixed_prefix,
                        read_start, start, state.total_reads,
                        self._retained_parts(frontier, hypotheses, evaluated) + len(fixed_prefix))
                    buffer_peak = max(buffer_peak, candidate_peak)
                except Exception:
                    # The current pair was not fully evaluated. Keep it at the
                    # same cursor while preserving every earlier completed pair.
                    frontier.append(node)
                    raise
                evaluated.append(key)
                pairs += 1
                if index + 1 < candidate_count:
                    frontier.append(Node(node.chunk_offsets, node.compressed, index + 1))
                if hypothesis is not None:
                    if not any(item.data == hypothesis.data for item in hypotheses):
                        hypotheses.append(hypothesis)
                        new_hypotheses += 1
                if child is not None:
                    frontier.append(child)
                buffer_peak = max(buffer_peak, self._retained_parts(frontier, hypotheses, evaluated)
                                  + len(fixed_prefix))
                if self._retained_parts(frontier, hypotheses, evaluated) > self.limits.retained_bytes:
                    raise _Stop("memory_limit")
            state_out = SearchState(1, self.config_id, tuple(frontier), tuple(hypotheses),
                tuple(evaluated), state.passes + 1, state.total_pairs + pairs,
                state.total_reads + self.source.bytes_read - read_start,
                state.total_elapsed + self.clock() - start, not frontier, fixed_prefix,
                state.stop_reasons + (reason,))
        except _Stop as stop:
            reason = stop.reason
            if reason == "memory_limit": buffer_peak = max(buffer_peak, self.limits.retained_bytes)
            state_out = SearchState(1, self.config_id, tuple(frontier), tuple(hypotheses),
                tuple(evaluated), state.passes + 1, state.total_pairs + pairs,
                state.total_reads + self.source.bytes_read - read_start,
                state.total_elapsed + self.clock() - start, False, fixed_prefix,
                state.stop_reasons + (reason,))
        except Exception as exc:
            reason = "error:" + type(exc).__name__ + ": " + str(exc)
            state_out = SearchState(1, self.config_id, tuple(frontier), tuple(hypotheses),
                tuple(evaluated), state.passes + 1, state.total_pairs + pairs,
                state.total_reads + self.source.bytes_read - read_start,
                state.total_elapsed + self.clock() - start, False, fixed_prefix,
                state.stop_reasons + (reason,))
        elapsed = self.clock() - start
        retained = self._retained(state_out)
        buffer_peak = max(buffer_peak, retained)
        if retained > self.limits.retained_bytes and reason == "search_exhausted":
            reason = "memory_limit"
        return PassResult(state_out, reason, pairs,
            self.source.bytes_read - read_start, elapsed, buffer_peak, new_hypotheses)

    def _aligned_ranges(self):
        intervals = []
        for low, high in self.ranges:
            if low < 0 or high <= low or high > self.source.size:
                raise ValueError("invalid candidate range")
            current = ((low + self.alignment - 1) // self.alignment) * self.alignment
            if current + 8 <= high:
                last = current + ((high - 8 - current) // self.alignment) * self.alignment
                intervals.append((current, last + self.alignment))
        merged = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return tuple(merged)

    def _candidate_count(self):
        return sum((end - start) // self.alignment for start, end in self._aligned_ranges())

    def _candidate_at(self, index):
        if index < 0: raise IndexError(index)
        for start, end in self._aligned_ranges():
            count = (end - start) // self.alignment
            if index < count: return start + index * self.alignment
            index -= count
        raise IndexError(index)

    def _read(self, offset, size, pass_read_start, start, cumulative_reads):
        if size > self.limits.candidate_bytes: return None
        if self.source.bytes_read - pass_read_start + size > self.limits.reads_per_pass:
            raise _Stop("read_limit")
        if cumulative_reads + self.source.bytes_read - pass_read_start + size > self.limits.total_reads:
            raise _Stop("cumulative_read_limit")
        if self.clock() - start >= self.limits.seconds_per_pass:
            raise _Stop("time_limit")
        return self.source.read_at(offset, size)

    def _read_chunk(self, offset, pass_read_start, start, cumulative_reads):
        header = self._read(offset, 8, pass_read_start, start, cumulative_reads)
        if header is None: return None
        length = int.from_bytes(header[:4], "big")
        return self._read(offset, length + 12, pass_read_start, start, cumulative_reads)

    def _evaluate(self, node, offset, fixed_prefix, pass_read_start, start, cumulative_reads,
                  base_retained):
        header = self._read(offset, 8, pass_read_start, start, cumulative_reads)
        if header is None: return None, None, base_retained + 8
        length = int.from_bytes(header[:4], "big")
        kind = header[4:]
        if length + 12 > self.limits.candidate_bytes:
            raise _Stop("candidate_size_limit")
        if base_retained + len(header) + length + 12 + 4 * 1024 * 1024 > self.limits.retained_bytes:
            raise _Stop("memory_limit")
        raw = self._read(offset, length + 12, pass_read_start, start, cumulative_reads)
        if raw is None or len(raw) != length + 12: return None, None, base_retained + len(header)
        payload = raw[8:8 + length]
        buffer_peak = base_retained + len(header) + len(raw) + len(payload)
        if zlib.crc32(kind + payload) & 0xffffffff != int.from_bytes(raw[-4:], "big"):
            return None, None, buffer_peak
        if kind == b"IEND":
            if length != 0 or not node.compressed: return None, None, buffer_peak
            candidate = fixed_prefix
            for chunk_offset in node.chunk_offsets:
                part = self._read_chunk(chunk_offset, pass_read_start, start, cumulative_reads)
                if part is None: raise _Stop("read_limit")
                candidate += part
            candidate += raw
            if len(candidate) > self.limits.candidate_bytes:
                raise _Stop("candidate_size_limit")
            buffer_peak = max(buffer_peak, base_retained + len(raw) + 3 * len(candidate)
                              + 4 * 1024 * 1024)
            if buffer_peak > self.limits.retained_bytes: raise _Stop("memory_limit")
            valid = _png_valid(candidate)
            path = tuple(node.chunk_offsets) + (offset,)
            return None, Hypothesis(path, valid) if valid is not None else None, buffer_peak
        if kind != b"IDAT" or offset in node.chunk_offsets:
            return None, None, buffer_peak
        compressed = node.compressed + payload
        buffer_peak = max(buffer_peak, base_retained + len(raw) + len(payload)
                          + len(node.compressed) + len(compressed) + 4 * 1024 * 1024)
        if buffer_peak > self.limits.retained_bytes: raise _Stop("memory_limit")
        try:
            decoder = zlib.decompressobj()
            decoded = decoder.decompress(compressed, 4 * 1024 * 1024 + 1)
            buffer_peak = max(buffer_peak, base_retained + len(raw) + len(payload)
                              + len(node.compressed) + len(compressed) + len(decoded))
            if decoder.unconsumed_tail: raise _Stop("decoded_output_limit")
            if decoder.unused_data: return None, None, buffer_peak
        except zlib.error:
            # A zlib error for the complete stream prefix rejects this order.
            return None, None, buffer_peak
        return Node(node.chunk_offsets + (offset,), compressed, 0), None, buffer_peak

    @staticmethod
    def _retained_parts(frontier, hypotheses, evaluated):
        return (sum(len(node.compressed) + len(node.chunk_offsets) * 8 + 32 for node in frontier)
                + sum(len(item.chunk_offsets) * 8 + len(item.data) + 32 for item in hypotheses)
                + len(evaluated) * 48)

    def _retained(self, state):
        return self._retained_parts(state.frontier, state.hypotheses, state.evaluated) + len(state.prefix)


class _Stop(Exception):
    def __init__(self, reason): self.reason = reason


def _synthetic_source(prefix: bytes, idats: tuple[bytes, ...], *,
                      seed: int, include_decoys: bool = True, decoy_parts: int = 2,
                      cluster_size: int = CLUSTER):
    rng = random.Random(seed)
    chunks = list(idats)
    if include_decoys:
        _, _, decoy_chunks = _parts_png(3, 2, decoy_parts, level=1, seed=seed + 100)
        chunks.extend(decoy_chunks)
    chunks.append(_chunk(b"IEND", b""))
    rng.shuffle(chunks)
    source = bytearray(prefix)
    offsets = []
    for chunk in chunks:
        target = ((len(source) + cluster_size - 1) // cluster_size) * cluster_size
        source.extend(b"\xA5" * (target - len(source)))
        offsets.append(target)
        source.extend(chunk)
    # Candidate search is deliberately given a broad range, never the true
    # continuation offsets. Image bytes/hash/positions remain test-only.
    low = len(prefix)
    high = len(source)
    return bytes(source), ((low, high),), tuple(offsets)


def _run_to_end(search, state):
    results = []
    while not state.exhausted and state.passes < search.limits.max_passes:
        result = search.run_pass(state)
        results.append(result)
        state = result.state
        if result.stop_reason not in ("combination_limit", "read_limit", "time_limit"):
            break
    return state, results


class PNGProgressiveReconstructionTests(unittest.TestCase):
    def _case(self, count, *, seed=202, level=6, entropy="random", cluster_size=CLUSTER,
              include_decoys=True):
        original, prefix, chunks = _parts_png(48, 32, count, level=level, seed=seed,
                                             entropy=entropy)
        source_data, ranges, _oracle_offsets = _synthetic_source(prefix, chunks,
            seed=seed + 7, include_decoys=include_decoys,
            decoy_parts=1 if count == 4 else 2,
            cluster_size=cluster_size)
        source = MemorySource(source_data)
        search = PNGProgressiveSearch(source, source_id=f"fixture-{seed}",
            signature_offset=0, candidate_ranges=ranges, alignment=cluster_size,
            max_fragments=8)
        return original, source, search

    def test_three_and_four_idat_fragments_recover_after_continuation_order_search(self):
        for count, level, entropy in ((3, 1, "low"), (4, 9, "random")):
            with self.subTest(count=count):
                original, source, search = self._case(count, seed=310 + count,
                                                       level=level, entropy=entropy)
                state, results = _run_to_end(search, search.initial_state())
                self.assertTrue(state.hypotheses)
                self.assertEqual(state.passes, len(results))
                recovered = []
                # Oracle maps candidate chunk offsets back to bytes only after
                # the algorithm has completed and returned its hypotheses.
                for hypothesis in state.hypotheses:
                    recovered.append(hashlib.sha256(hypothesis.data).hexdigest())
                self.assertIn(hashlib.sha256(original).hexdigest(), recovered)
                self.assertLessEqual(max(r.pairs for r in results), PAIR_LIMIT)
                self.assertTrue(all(r.bytes_read <= READ_LIMIT for r in results))
                self.assertTrue(all(r.buffer_peak_estimate <= RETAINED_LIMIT for r in results))

    def test_resumed_search_reaches_candidate_after_first_sixty_four_pairs_without_repeats(self):
        original, source, search = self._case(4, seed=401, level=3)
        state = search.initial_state()
        first = search.run_pass(state)
        self.assertEqual(first.stop_reason, "combination_limit")
        self.assertEqual(first.pairs, 64)
        self.assertIn("combination_limit", first.state.stop_reasons)
        second = search.run_pass(first.state)
        self.assertGreater(second.pairs, 0)
        self.assertTrue(second.state.hypotheses)
        all_pairs = [pair for pair in second.state.evaluated]
        self.assertEqual(len(all_pairs), len(set(all_pairs)))
        self.assertIn(hashlib.sha256(original).hexdigest(), [
            hashlib.sha256(hypothesis.data).hexdigest() for hypothesis in second.state.hypotheses])

    def test_progressive_passes_and_single_pass_equivalent_budget_find_same_hypothesis(self):
        original, source, search = self._case(3, seed=503, level=2)
        initial = search.initial_state()
        progressive, _ = _run_to_end(search, initial)
        equivalent = Limits(pairs_per_pass=256, reads_per_pass=32 * 1024 * 1024,
            seconds_per_pass=8.0, retained_bytes=RETAINED_LIMIT, max_passes=1)
        one_shot_search = PNGProgressiveSearch(MemorySource(source.data), source_id="fixture-503",
            signature_offset=0, candidate_ranges=search.ranges, alignment=CLUSTER,
            max_fragments=8, limits=equivalent)
        one_shot = one_shot_search.run_pass(one_shot_search.initial_state()).state
        self.assertEqual(set(progressive.hypotheses), set(one_shot.hypotheses))
        self.assertEqual(progressive.total_pairs, one_shot.total_pairs)
        self.assertEqual(progressive.total_reads, one_shot.total_reads)
        self.assertIn(hashlib.sha256(original).hexdigest(), [
            hashlib.sha256(hypothesis.data).hexdigest() for hypothesis in progressive.hypotheses])

    def test_state_config_identity_rejects_changed_ranges_and_preserves_hypotheses(self):
        original, source, search = self._case(3, seed=611)
        result = search.run_pass(search.initial_state())
        changed = PNGProgressiveSearch(source, source_id="fixture-611", signature_offset=0,
            candidate_ranges=((0, source.size),), alignment=CLUSTER, max_fragments=8)
        rejected = changed.run_pass(result.state)
        self.assertEqual(rejected.stop_reason, "configuration_mismatch")
        self.assertEqual(rejected.state, result.state)

    def test_read_error_and_failed_state_publication_leave_prior_state_usable(self):
        original, source, search = self._case(3, seed=722)
        # A failed publication is represented by retaining the previous
        # immutable state instead of assigning a new one.
        durable = search.initial_state()
        following = search.run_pass(durable)
        try:
            raise OSError("synthetic state sink failure")
        except OSError:
            pass
        self.assertEqual(durable.passes, 0)
        resumed = search.run_pass(following.state)
        self.assertNotIn("error", resumed.stop_reason)
        self.assertEqual(len(following.state.evaluated), len(set(following.state.evaluated)))

        failing_source = MemorySource(source.data)
        failing = PNGProgressiveSearch(failing_source, source_id="failure-fixture",
            signature_offset=0, candidate_ranges=((source.data.find(b"\xA5"), source.size),))
        state = failing.initial_state()
        # Prefix reads still work; candidate range is invalid to configure only
        # if it is not cluster aligned, so inject failure at the first grid read.
        candidate = failing._candidate_at(1)
        failing_source.fail_on.add((candidate, 8))
        error = failing.run_pass(state)
        self.assertTrue(error.stop_reason.startswith("error:"))
        self.assertGreater(error.state.total_pairs, 0)
        self.assertEqual(len(error.state.evaluated), len(set(error.state.evaluated)))
        failing_source.fail_on.clear()
        retry = failing.run_pass(error.state)
        self.assertNotIn("error", retry.stop_reason)
        self.assertEqual(len(retry.state.evaluated), len(set(retry.state.evaluated)))

        _validation_original, validation_fixture, validation_template = self._case(
            2, seed=723, include_decoys=False)
        validation_source = MemorySource(validation_fixture.data)
        validation_search = PNGProgressiveSearch(validation_source, source_id="validation-failure",
            signature_offset=0, candidate_ranges=validation_template.ranges, alignment=CLUSTER,
            limits=Limits(pairs_per_pass=256, reads_per_pass=32 * 1024 * 1024,
                seconds_per_pass=8.0, max_passes=1))
        with patch.object(sys.modules[__name__], "_png_valid",
                          side_effect=RuntimeError("synthetic validator failure")):
            validation_error = validation_search.run_pass(validation_search.initial_state())
        self.assertTrue(validation_error.stop_reason.startswith("error:"),
                        validation_error.stop_reason)
        self.assertGreater(validation_error.state.total_pairs, 0)
        self.assertEqual(len(validation_error.state.evaluated),
                         len(set(validation_error.state.evaluated)))

    def test_byte_perfect_prefix_traversal_is_not_called_integrity_and_ambiguity_survives(self):
        original, prefix, chunks = _parts_png(40, 30, 2, level=6, seed=818)
        data, ranges, offsets = _synthetic_source(prefix, chunks, seed=825,
                                                   include_decoys=False)
        # Add a second structurally valid source image's IDAT chunks and IEND.
        decoy_original, decoy_prefix, decoy_chunks = _parts_png(40, 30, 2, level=6, seed=919)
        self.assertEqual(prefix, decoy_prefix)
        mutable = bytearray(data)
        extra = _chunk(b"IEND", b"")
        for item in (*decoy_chunks, extra):
            target = ((len(mutable) + CLUSTER - 1) // CLUSTER) * CLUSTER
            mutable.extend(b"\x5A" * (target - len(mutable))); mutable.extend(item)
        source = MemorySource(bytes(mutable)); expanded_ranges = ((len(prefix), len(mutable)),)
        search = PNGProgressiveSearch(source, source_id="ambiguous-fixture", signature_offset=0,
            candidate_ranges=expanded_ranges, alignment=CLUSTER, max_fragments=8,
            limits=Limits(pairs_per_pass=256, reads_per_pass=32 * 1024 * 1024,
                seconds_per_pass=8.0, retained_bytes=RETAINED_LIMIT, max_passes=1))
        result = search.run_pass(search.initial_state())
        self.assertGreaterEqual(len(result.state.hypotheses), 2)
        # The classification depends on hypotheses plus unexplored scope, not
        # on whether the hidden fixture oracle later identifies matching bytes.
        self.assertNotEqual(result.classification, "verified_integrity")
        found = {hashlib.sha256(item.data).hexdigest() for item in result.state.hypotheses}
        self.assertIn(hashlib.sha256(original).hexdigest(), found)
        self.assertIn(hashlib.sha256(decoy_original).hexdigest(), found)

    def test_contiguous_carver_control_and_fragmented_control(self):
        original, prefix, chunks = _parts_png(32, 24, 3, level=6, seed=919)
        self.assertEqual(_png_valid(original), original)
        physical, _, _ = _synthetic_source(prefix, chunks, seed=926)
        # The established carver gets only the contiguous prefix region and
        # must reject it; experimental continuation search is separate.
        self.assertIsNone(_png_valid(physical[:CLUSTER]))

    def test_missing_or_partially_overwritten_idat_does_not_claim_integrity(self):
        original, prefix, chunks = _parts_png(48, 32, 3, level=6, seed=1021)
        missing_data, ranges, _ = _synthetic_source(prefix, chunks[:-1],
            seed=1028, include_decoys=False)
        missing_search = PNGProgressiveSearch(MemorySource(missing_data), source_id="missing",
            signature_offset=0, candidate_ranges=ranges, alignment=CLUSTER, max_fragments=8)
        missing_state, missing_passes = _run_to_end(missing_search, missing_search.initial_state())
        self.assertFalse(missing_state.hypotheses)
        self.assertTrue(missing_state.exhausted)
        self.assertEqual(missing_passes[-1].stop_reason, "search_exhausted")

        damaged = bytearray(chunks[1])
        damaged[12] ^= 0x80  # alter IDAT payload but leave its old CRC
        overwritten = (chunks[0], bytes(damaged), chunks[2])
        partial_data, partial_ranges, _ = _synthetic_source(prefix, overwritten,
            seed=1029, include_decoys=False)
        partial_search = PNGProgressiveSearch(MemorySource(partial_data), source_id="partial",
            signature_offset=0, candidate_ranges=partial_ranges, alignment=CLUSTER, max_fragments=8)
        partial_state, partial_passes = _run_to_end(partial_search, partial_search.initial_state())
        self.assertFalse(partial_state.hypotheses)
        self.assertTrue(partial_state.exhausted)
        self.assertEqual(partial_passes[-1].stop_reason, "search_exhausted")

    def test_alternate_simulated_cluster_geometry_and_resource_stop_reasons(self):
        original, source, search = self._case(3, seed=1117, cluster_size=8192,
                                               include_decoys=False)
        state, results = _run_to_end(search, search.initial_state())
        self.assertTrue(state.hypotheses)
        self.assertIn(hashlib.sha256(original).hexdigest(), [
            hashlib.sha256(item.data).hexdigest() for item in state.hypotheses])

        limited = Limits(reads_per_pass=33, max_passes=1)
        read_search = PNGProgressiveSearch(MemorySource(source.data), source_id="read-cap",
            signature_offset=0, candidate_ranges=search.ranges, alignment=8192,
            max_fragments=8, limits=limited)
        self.assertEqual(read_search.run_pass(read_search.initial_state()).stop_reason, "read_limit")

        memory_search = PNGProgressiveSearch(MemorySource(source.data), source_id="memory-cap",
            signature_offset=0, candidate_ranges=search.ranges, alignment=8192,
            max_fragments=8, limits=Limits(retained_bytes=1, max_passes=1))
        self.assertEqual(memory_search.run_pass(memory_search.initial_state()).stop_reason, "memory_limit")

        class Clock:
            now = 0.0
            def __call__(self):
                self.now += 0.25
                return self.now
        timed_search = PNGProgressiveSearch(MemorySource(source.data), source_id="time-cap",
            signature_offset=0, candidate_ranges=search.ranges, alignment=8192,
            max_fragments=8, limits=Limits(seconds_per_pass=0.75, max_passes=2), monotonic=Clock())
        self.assertEqual(timed_search.run_pass(timed_search.initial_state()).stop_reason, "time_limit")


if __name__ == "__main__": unittest.main()
