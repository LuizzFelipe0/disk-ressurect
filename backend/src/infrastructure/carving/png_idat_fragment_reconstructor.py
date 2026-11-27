"""Bounded recovery of PNGs whose complete IDAT chunks are cluster aligned.

This is an opt-in advanced strategy. It does not reconstruct arbitrary cuts or
infer the original file's integrity; it returns structural hypotheses only.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import hashlib
import time
import zlib

from infrastructure.carving.content_carver import CarvedContent, RawContentCarver


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class PNGReconstructionResult:
    candidates: tuple[CarvedContent, ...]
    signatures_seen: int
    signatures_examined: int
    combinations: int
    bytes_read: int
    elapsed_seconds: float
    retained_bytes_estimate: int
    stop_reason: str


@dataclass
class _SearchNode:
    offsets: tuple[int, ...]
    compressed: bytes
    next_candidate: int
    spans: tuple[tuple[int, int], ...] = ()


class PNGIDATFragmentReconstructor:
    """Search eligible ranges for complete, aligned IDAT chunks and IEND."""

    MAX_SIGNATURES = 4
    PAIRS_PER_PASS = 64
    MAX_PASSES = 4
    READS_PER_PASS = 8 * 1024 * 1024
    MAX_CANDIDATE_BYTES = 2 * 1024 * 1024
    SECONDS_PER_PASS = 2.0
    RETAINED_BYTES = 16 * 1024 * 1024
    PNG_DECODED_BYTES = 4 * 1024 * 1024
    TRANSIENT_BUFFER_ESTIMATE = 8 * 1024 * 1024

    def __init__(self, source, *, volume_start, volume_end, cluster_size,
                 monotonic=time.monotonic):
        self.source = source
        self.volume_start = int(volume_start)
        self.volume_end = int(volume_end)
        self.cluster_size = int(cluster_size)
        self.clock = monotonic
        self._read_count = 0
        if self.volume_start < 0 or self.volume_end <= self.volume_start or self.cluster_size <= 0:
            raise ValueError("volume bounds and cluster size must be positive")

    def reconstruct(self, signature_offsets, eligible_ranges, *, prior_combinations=0,
                    prior_bytes_read=0, prior_elapsed_seconds=0.0,
                    prior_retained_bytes=0):
        self._read_count = 0
        started = self.clock()
        budget_started = started - max(0.0, float(prior_elapsed_seconds))
        ranges = self._validate_ranges(eligible_ranges)
        signatures = tuple(sorted(set(int(item) for item in signature_offsets)))
        if any(item < self.volume_start or item >= self.volume_end for item in signatures):
            raise ValueError("PNG signature is outside the volume")
        candidates = []
        candidate_data_seen = set()
        examined = pairs = bytes_read = 0
        peak = max(0, int(prior_retained_bytes))
        stop_reason = "search_exhausted"
        for signature in signatures[:self.MAX_SIGNATURES]:
            examined += 1
            found, attempted, consumed, retained, reason = self._search_one(
                signature, ranges, budget_started,
                int(prior_combinations) + pairs,
                int(prior_bytes_read) + bytes_read,
                max(0, int(prior_retained_bytes))
                + sum(len(item.data) for item in candidates),
            )
            if len(found) > 1:
                hypothesis_status = "multiple_competing_hypotheses"
            elif found and reason == "search_exhausted":
                hypothesis_status = "unique_hypothesis_in_scope"
            elif found and reason in {"read_error", "search_error", "invalid_prefix"}:
                hypothesis_status = "inconclusive_search"
            elif found:
                hypothesis_status = "resource_limited_search"
            else:
                hypothesis_status = "inconclusive_search" if reason != "search_exhausted" else "rejected"
            found = tuple(replace(
                item,
                evidence={
                    **(item.evidence or {}),
                    "hypothesisStatus": hypothesis_status,
                    "searchComplete": reason == "search_exhausted",
                    "searchStopReason": reason,
                },
            ) for item in found)
            for item in found:
                digest = hashlib.sha256(item.data).digest()
                if digest not in candidate_data_seen:
                    candidate_data_seen.add(digest)
                    candidates.append(item)
            pairs += attempted
            bytes_read += consumed
            peak = max(peak, retained)
            if reason == "invalid_prefix":
                continue
            if reason != "search_exhausted":
                stop_reason = reason
                break
        else:
            if len(signatures) > self.MAX_SIGNATURES:
                stop_reason = "signature_limit"
        if stop_reason != "search_exhausted":
            if stop_reason in {"read_error", "search_error", "range_error", "invalid_prefix"}:
                status = "inconclusive_search"
            else:
                status = "resource_limited_search"
            candidates = [replace(
                item,
                evidence={
                    **(item.evidence or {}),
                    "hypothesisStatus": status,
                    "searchComplete": False,
                    "searchStopReason": stop_reason,
                },
            ) for item in candidates]
        return PNGReconstructionResult(
            tuple(candidates), len(signatures), examined, pairs, bytes_read,
            max(0.0, self.clock() - started), peak, stop_reason,
        )

    def _search_one(self, signature, ranges, experiment_start, prior_pairs, prior_reads,
                    retained_base):
        read_before_prefix = self._read_count
        try:
            prefix = self._read_prefix(signature, ranges, experiment_start, prior_reads)
        except _SearchStop as exc:
            return (), 0, self._read_count - read_before_prefix, 0, exc.reason
        except OSError:
            return (), 0, self._read_count - read_before_prefix, 0, "read_error"
        prefix_reads = self._read_count - read_before_prefix
        if prefix is None:
            return (), 0, 0, 0, "invalid_prefix"
        prefix_span = (signature, signature + len(prefix))
        candidate_count = self._candidate_count(ranges, (prefix_span,))
        frontier = [_SearchNode((), b"", 0, ())]
        hypotheses = {}
        evaluated = set()
        pairs = reads_total = 0
        peak = retained_base + len(prefix)
        stop_reason = "search_exhausted"
        for pass_index in range(self.MAX_PASSES):
            pass_started = self.clock()
            pass_reads = prefix_reads if pass_index == 0 else 0
            pass_pairs = 0
            while frontier:
                if self.clock() - pass_started >= self.SECONDS_PER_PASS:
                    stop_reason = "time_limit"
                    break
                node = frontier.pop()
                if node.next_candidate >= candidate_count:
                    continue
                if (self._retained(frontier, hypotheses, evaluated, prefix, retained_base)
                        + self.TRANSIENT_BUFFER_ESTIMATE > self.RETAINED_BYTES):
                    frontier.append(node)
                    stop_reason = "memory_limit"
                    break
                if pass_pairs >= self.PAIRS_PER_PASS:
                    frontier.append(node)
                    stop_reason = "combination_limit"
                    break
                if (prior_pairs + pairs) >= self.PAIRS_PER_PASS * self.MAX_PASSES:
                    frontier.append(node)
                    stop_reason = "cumulative_combination_limit"
                    break
                if self.clock() - experiment_start >= self.SECONDS_PER_PASS * self.MAX_PASSES:
                    frontier.append(node)
                    stop_reason = "cumulative_time_limit"
                    break
                offset = self._candidate_at(ranges, node.next_candidate, (prefix_span,))
                key = node.offsets, offset
                if key in evaluated:
                    stop_reason = "search_error"
                    break
                before_evaluation = self._read_count
                try:
                    child, hypothesis, used, retained, reason = self._evaluate(
                        signature, node, offset, prefix, ranges, pass_reads,
                        experiment_start, prior_reads + prefix_reads + reads_total,
                    )
                except _SearchStop as exc:
                    failed_bytes = self._read_count - before_evaluation
                    pass_reads += failed_bytes
                    reads_total += failed_bytes
                    pairs += 1
                    pass_pairs += 1
                    frontier.append(node)
                    stop_reason = exc.reason
                    break
                except OSError:
                    failed_bytes = self._read_count - before_evaluation
                    pass_reads += failed_bytes
                    reads_total += failed_bytes
                    pairs += 1
                    pass_pairs += 1
                    frontier.append(node)
                    stop_reason = "read_error"
                    break
                actual_bytes = self._read_count - before_evaluation
                pass_reads += actual_bytes
                reads_total += actual_bytes
                evaluated.add(key)
                pairs += 1
                pass_pairs += 1
                next_frontier = list(frontier)
                if node.next_candidate + 1 < candidate_count:
                    next_frontier.append(_SearchNode(
                        node.offsets, node.compressed, node.next_candidate + 1, node.spans,
                    ))
                if child is not None:
                    next_frontier.append(child)
                next_hypotheses = dict(hypotheses)
                if hypothesis is not None:
                    next_hypotheses[hypothesis.data] = hypothesis
                retained_state = self._retained(
                    next_frontier, next_hypotheses, evaluated, prefix, retained_base,
                )
                peak = max(peak, retained_state, retained)
                if max(retained, retained_state) > self.RETAINED_BYTES:
                    stop_reason = "memory_limit"
                    break
                frontier = next_frontier
                hypotheses = next_hypotheses
                if pass_reads >= self.READS_PER_PASS:
                    stop_reason = "read_limit"
                    break
            if stop_reason in {"combination_limit", "read_limit", "time_limit"}:
                if pass_index + 1 < self.MAX_PASSES:
                    stop_reason = "search_exhausted"
                    continue
                if stop_reason == "combination_limit":
                    stop_reason = "cumulative_combination_limit"
            if stop_reason != "search_exhausted" or not frontier:
                break
            if pass_index + 1 == self.MAX_PASSES:
                stop_reason = "cumulative_combination_limit" if frontier else "search_exhausted"
        return tuple(hypotheses.values()), pairs, prefix_reads + reads_total, peak, stop_reason

    @staticmethod
    def _retained(frontier, hypotheses, evaluated, prefix, retained_base):
        return (
            retained_base + len(prefix)
            + sum(len(node.compressed) + len(node.offsets) * 8 + 32 for node in frontier)
            + sum(len(candidate.data) + 96 for candidate in hypotheses.values())
            + len(evaluated) * 48
        )

    def _evaluate(self, signature, node, offset, prefix, ranges, pass_reads, started,
                  prior_reads):
        interval = next(((low, high) for low, high in ranges if low <= offset < high), None)
        if interval is None:
            return None, None, 0, 0, "search_exhausted"
        low, high = interval
        header = self._bounded_read(offset, 8, low, high, pass_reads, started, prior_reads)
        if header is None:
            return None, None, 8, 0, "search_exhausted"
        length = int.from_bytes(header[:4], "big")
        total = length + 12
        if total > self.MAX_CANDIDATE_BYTES:
            return None, None, 8, 0, "search_exhausted"
        raw = self._bounded_read(offset, total, low, high, pass_reads + 8,
                                 started, prior_reads + 8)
        used = 8 + total
        if raw is None:
            return None, None, used, 0, "search_exhausted"
        kind, payload = raw[4:8], raw[8:-4]
        if zlib.crc32(kind + payload) & 0xffffffff != int.from_bytes(raw[-4:], "big"):
            return None, None, used, len(raw), "search_exhausted"
        current_span = (offset, offset + total)
        occupied_spans = node.spans + ((signature, signature + len(prefix)),)
        if any(current_span[0] < end and start < current_span[1]
               for start, end in occupied_spans):
            return None, None, used, len(raw), "search_exhausted"
        if kind == b"IDAT":
            if len(node.offsets) >= 4 or offset in node.offsets:
                return None, None, used, len(raw), "search_exhausted"
            compressed = node.compressed + payload
            try:
                decoder = zlib.decompressobj()
                decoded = decoder.decompress(compressed, self.PNG_DECODED_BYTES + 1)
                if decoder.unconsumed_tail or decoder.unused_data:
                    return None, None, used, len(compressed) + len(decoded), "search_exhausted"
            except zlib.error:
                return None, None, used, len(compressed), "search_exhausted"
            return (_SearchNode(node.offsets + (offset,), compressed, 0,
                                node.spans + (current_span,)), None,
                    used, len(compressed) + len(decoded), "search_exhausted")
        if kind != b"IEND" or length != 0 or not node.offsets:
            return None, None, used, len(raw), "search_exhausted"
        data = bytearray(prefix)
        for chunk_offset in node.offsets:
            chunk_range = next(((a, b) for a, b in ranges if a <= chunk_offset < b), None)
            if chunk_range is None:
                return None, None, used, len(data), "search_exhausted"
            chunk_len_header = self._bounded_read(
                chunk_offset, 8, *chunk_range, pass_reads + used, started,
                prior_reads + used,
            )
            if chunk_len_header is None:
                raise _SearchStop("range_error")
            chunk_size = int.from_bytes(chunk_len_header[:4], "big") + 12
            chunk = self._bounded_read(
                chunk_offset, chunk_size, *chunk_range, pass_reads + used + 8,
                started, prior_reads + used + 8,
            )
            used += 8 + chunk_size
            if chunk is None:
                raise _SearchStop("range_error")
            data.extend(chunk)
        data.extend(raw)
        if len(data) > self.MAX_CANDIDATE_BYTES:
            return None, None, used, len(data), "search_exhausted"
        if self._validate_png(bytes(data)):
            from infrastructure.carving.content_carver import CarvedContent
            evidence = {
                "strategy": "aligned_complete_idat_chunks",
                "signatureOffset": signature,
                "sourceRanges": ((signature, signature + len(prefix)),)
                + node.spans + (current_span,),
                "orderedFragments": ((0, signature, signature + len(prefix)),)
                + tuple(
                    (index + 1, start, end)
                    for index, (start, end) in enumerate(node.spans)
                ) + ((len(node.offsets) + 1, current_span[0], current_span[1]),),
                "validation": "png_structure_hypothesis",
            }
            candidate = CarvedContent(
                offset=signature, extension=".png", data=bytes(data),
                strategy="png_fragment_reconstruction", evidence=evidence,
            )
            estimated = len(data) * 3 + self.PNG_DECODED_BYTES + len(prefix) + 4 * 1024 * 1024
            return None, candidate, used, estimated, "search_exhausted"
        return None, None, used, len(data), "search_exhausted"

    def _read_prefix(self, signature, ranges, started, total_reads):
        interval = next(
            ((low, high) for low, high in ranges if low <= signature < high),
            None,
        )
        if interval is None:
            return None
        low, high = interval
        if signature < self.volume_start or signature + 33 > min(high, self.volume_end):
            return None
        raw = self._bounded_read(
            signature, 33, low, high, 0, started, total_reads,
        )
        if raw is None or not raw.startswith(PNG_SIGNATURE):
            return None
        length = int.from_bytes(raw[8:12], "big")
        if length != 13:
            return None
        if zlib.crc32(raw[12:29]) & 0xffffffff != int.from_bytes(raw[29:33], "big"):
            return None
        return raw

    def _bounded_read(self, offset, size, low, high, pass_reads, started, total_reads):
        if (size < 0 or size > self.MAX_CANDIDATE_BYTES or offset < low
                or offset + size > high):
            return None
        if pass_reads + size > self.READS_PER_PASS:
            raise _SearchStop("read_limit")
        if total_reads + size > self.READS_PER_PASS * self.MAX_PASSES:
            raise _SearchStop("cumulative_read_limit")
        if self.clock() - started >= self.SECONDS_PER_PASS * self.MAX_PASSES:
            raise _SearchStop("time_limit")
        data = bytes(self.source.read_at(offset, size))
        self._read_count += len(data)
        if len(data) != size:
            raise OSError(f"Short PNG reconstruction read at {offset:#x}")
        return data

    def _candidate_count(self, ranges, excluded=()):
        count = 0
        for low, high in ranges:
            first_index = max(0, (low - self.volume_start + self.cluster_size - 1)
                              // self.cluster_size)
            last_index = (high - 8 - self.volume_start) // self.cluster_size
            if last_index < first_index:
                continue
            count += last_index - first_index + 1
            for start, end in excluded:
                excluded_first = max(
                    first_index,
                    (start - 7 - self.volume_start + self.cluster_size - 1)
                    // self.cluster_size,
                )
                excluded_last = min(
                    last_index,
                    (end - 1 - self.volume_start) // self.cluster_size,
                )
                count -= max(0, excluded_last - excluded_first + 1)
        return count

    def _candidate_at(self, ranges, index, excluded=()):
        for low, high in ranges:
            first_index = max(0, (low - self.volume_start + self.cluster_size - 1)
                              // self.cluster_size)
            last_index = (high - 8 - self.volume_start) // self.cluster_size
            for candidate_index in range(first_index, last_index + 1):
                offset = self.volume_start + candidate_index * self.cluster_size
                if any(offset < end and start < offset + 8 for start, end in excluded):
                    continue
                if index == 0:
                    return offset
                index -= 1
        raise IndexError(index)

    def _validate_ranges(self, ranges):
        normalized = []
        for start, end in ranges:
            start, end = int(start), int(end)
            if start < self.volume_start or end > self.volume_end or end <= start:
                raise ValueError("eligible range is outside the volume")
            normalized.append((start, end))
        normalized.sort()
        if any(left[1] > right[0] for left, right in zip(normalized, normalized[1:])):
            raise ValueError("eligible ranges overlap")
        return tuple(normalized)

    @staticmethod
    def _validate_png(data):
        class MemoryReader:
            size = len(data)
            def read_at(self, offset, size):
                return data[offset:offset + size]
        carver = RawContentCarver(
            MemoryReader(), max_file_bytes=len(data),
            max_decoded_png_bytes=PNGIDATFragmentReconstructor.PNG_DECODED_BYTES,
        )
        try:
            result, _, _ = carver._read_png(0, len(data), len(data) * 2)
            return result == data
        except (OSError, ValueError, TypeError, OverflowError, zlib.error):
            return False


class _SearchStop(Exception):
    def __init__(self, reason):
        self.reason = reason
