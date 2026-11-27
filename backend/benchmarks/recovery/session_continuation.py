"""Small in-memory benchmark of active-session PNG reconstruction continuation."""

from __future__ import annotations

import hashlib
import struct
import time
import zlib

from application.session import RecoverySession
from application.workflows.catalog_scan import CatalogScanWorkflow
from infrastructure.carving.content_carver import RawContentCarver
from infrastructure.carving.png_idat_fragment_reconstructor import PNGIDATFragmentReconstructor
from infrastructure.filesystems.ntfs.catalog_builder import CatalogBuilder
from modules.catalog.dto import CarvingOptionsDto
from modules.disk.entities import NTFSVolume
from modules.storage.entities import StorageSource

from .resource_measurement import measure


CLUSTER_SIZE = 4096
SIGNATURE_STRIDE = 2 * CLUSTER_SIZE
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, payload: bytes = b"") -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def _fixture(signature_count: int):
    """Return synthetic source, eligible range and test-only original bytes."""
    if signature_count not in (4, 5):
        raise ValueError("Session benchmark supports the four- and five-signature cases")

    width, height = 24, 12
    pixels = bytes((index * 37 + 11) & 0xFF for index in range(width * height * 3))
    raw_rows = b"".join(b"\0" + pixels[row * width * 3:(row + 1) * width * 3]
                       for row in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    prefix = PNG_SIGNATURE + _chunk(b"IHDR", ihdr)
    compressed = zlib.compress(raw_rows, 3)
    midpoint = max(2, len(compressed) // 2)
    idat_first = _chunk(b"IDAT", compressed[:midpoint])
    idat_second = _chunk(b"IDAT", compressed[midpoint:])
    iend = _chunk(b"IEND")
    original = prefix + idat_first + idat_second + iend

    target_index = signature_count - 1
    prefix_offset = target_index * SIGNATURE_STRIDE
    first_chunk_offset = prefix_offset + CLUSTER_SIZE
    foreign_offset = prefix_offset + 2 * CLUSTER_SIZE
    second_chunk_offset = prefix_offset + 3 * CLUSTER_SIZE
    iend_offset = prefix_offset + 4 * CLUSTER_SIZE
    data = bytearray(iend_offset + CLUSTER_SIZE)
    for index in range(signature_count - 1):
        offset = index * SIGNATURE_STRIDE
        data[offset:offset + len(PNG_SIGNATURE)] = PNG_SIGNATURE
        data[offset + len(PNG_SIGNATURE):offset + 32] = b"\0" * (32 - len(PNG_SIGNATURE))
    data[prefix_offset:prefix_offset + len(prefix)] = prefix
    data[first_chunk_offset:first_chunk_offset + len(idat_first)] = idat_first
    data[foreign_offset:foreign_offset + len(_chunk(b"tEXt", b"foreign"))] = _chunk(
        b"tEXt", b"foreign",
    )
    data[second_chunk_offset:second_chunk_offset + len(idat_second)] = idat_second
    data[iend_offset:iend_offset + len(iend)] = iend
    return bytes(data), ((0, len(data)),), original


class _Reader:
    def __init__(self, source, data, events):
        self.source = source
        self.data = data
        self.size = len(data)
        self.size_bytes = self.size
        self.bytes_per_sector = source.bytes_per_sector
        self.events = events

    def read_at(self, offset, size):
        offset, size = int(offset), int(size)
        if offset < 0 or size < 0 or offset + size > self.size:
            raise ValueError("Synthetic benchmark read escaped source bounds")
        self.events.append((offset, size))
        return self.data[offset:offset + size]

    def close(self):
        return None


class _SourceFactory:
    def __init__(self, data):
        self.data = data
        self.source = StorageSource(
            source_id="raw-image:png-session-benchmark",
            source_type="raw_image",
            display_name="Synthetic PNG session benchmark",
            size_bytes=len(data),
            bytes_per_sector=512,
            locator="in-memory-only",
        )
        self.events = []

    def get_source(self, source_id):
        if source_id != self.source.source_id:
            raise ValueError("Synthetic source identity mismatch")
        return self.source

    def __call__(self, source_id):
        return self.get_source(source_id)

    def open_reader(self, source):
        if source.source_id != self.source.source_id:
            raise ValueError("Synthetic source identity changed")
        return _Reader(source, self.data, self.events)


class _Validation:
    def __init__(self, ranges):
        self.ranges = ranges

    def validate_source(self, _source, *_args, retain_orphans_for_offset, **_kwargs):
        return {
            "orphan_records_by_partition": {retain_orphans_for_offset: {}},
            "content_carving_ranges_by_partition": {retain_orphans_for_offset: self.ranges},
            "content_carving_ranges_truncated_by_partition": {retain_orphans_for_offset: False},
        }

    @staticmethod
    def summary(_report):
        return {"coverageStatus": "synthetic", "assessment": "inconclusive"}


def _unique_bytes(events):
    intervals = sorted((offset, offset + size) for offset, size in events if size)
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return sum(end - start for start, end in merged)


def _run_case(signature_count):
    data, ranges, oracle_original = _fixture(signature_count)
    source_factory = _SourceFactory(data)
    session = RecoverySession()
    builder = CatalogBuilder(source_factory=source_factory)
    workflow = CatalogScanWorkflow(None, None, _Validation(ranges), builder, session=session)
    volume = NTFSVolume(
        -1, 1, 0, len(data), 512, CLUSTER_SIZE, 1024, 0, 0, (),
        "Synthetic NTFS", False, source_factory.source.source_id,
    )
    options = CarvingOptionsDto(enable_png_fragment_reconstruction=True)
    direct_reader = source_factory.open_reader(source_factory.source)
    contiguous = RawContentCarver(direct_reader).scan(ranges)
    direct_reader.close()
    contiguous_png_count = sum(item.extension == ".png" for item in contiguous.files)
    contiguous_read_bytes = sum(size for _offset, size in source_factory.events)
    contiguous_unique_bytes = _unique_bytes(source_factory.events)
    source_factory.events.clear()

    snapshots = []
    passes = 0
    started = time.perf_counter()
    while passes < 8:
        outcome = workflow.run(
            volume,
            include_orphaned=True,
            force_fresh_validation=True,
            carving_options=options,
            progress_callback=lambda *_args: None,
            validation_progress_callback=lambda *_args: None,
            phase_callback=lambda *_args: None,
        )
        snapshots.append(outcome.snapshot)
        session.set_catalog(outcome.snapshot)
        passes += 1
        if (outcome.snapshot.content_carving_summary or {}).get("stopReason") == "scope_complete":
            break
    elapsed = time.perf_counter() - started
    if not snapshots or (snapshots[-1].content_carving_summary or {}).get("stopReason") != "scope_complete":
        raise AssertionError("Synthetic session did not complete its declared PNG search scope")

    snapshot = snapshots[-1]
    candidates = [
        node.candidate for node in snapshot.catalog.nodes.values()
        if node.candidate is not None
        and "fragment_reconstruction" in node.candidate.discovery_methods
    ]
    oracle_digest = hashlib.sha256(oracle_original).hexdigest()
    exact = sum(
        candidate.content_reference is not None
        and candidate.content_reference.sha256 == oracle_digest
        for candidate in candidates
    )
    progress = snapshot.png_recovery_progress
    summary = (snapshot.content_carving_summary or {}).get("pngFragmentReconstruction", {})
    return {
        "signatureCount": signature_count,
        "passes": passes,
        "contiguousPngCandidates": contiguous_png_count,
        "contiguousReadBytesTotal": contiguous_read_bytes,
        "contiguousReadBytesUnique": contiguous_unique_bytes,
        "completeReconstructionHypotheses": len(candidates),
        "exactOriginalMatchesAfterSearch": exact,
        "incorrectOrCompetingHypotheses": len(candidates) - exact,
        "uniqueSignaturesExamined": progress.reconstruction_signatures_considered,
        "pendingSignatures": max(
            0, progress.discovered_signatures - progress.reconstruction_signatures_considered,
        ),
        "combinationsEvaluated": progress.reconstruction_combinations,
        "reconstructionBytesRead": progress.reconstruction_bytes_read,
        "sourceReadBytesTotal": sum(size for _offset, size in source_factory.events),
        "sourceReadBytesUnique": _unique_bytes(source_factory.events),
        "sessionRetainedBytesEstimate": session.raw_catalog_retained_bytes,
        "sessionCheckpointBytesEstimate": session.raw_carving_checkpoint_memory_bytes,
        "stopReason": summary.get("stopReason", "not_reported"),
        "scopeStopReason": (snapshot.content_carving_summary or {}).get("stopReason"),
        "wallSeconds": elapsed,
        "knownOriginalSha256": oracle_digest,
        "oraclePassedIntoSearch": False,
        "oraclePositionsPassedIntoSearch": False,
    }


def run_session_continuation_benchmark():
    """Compare a four-signature control with recovery on the fifth signature."""
    cases = []
    measurements = []
    for count in (4, 5):
        result, measured = measure(lambda count=count: _run_case(count))
        cases.append(result)
        measurements.append(measured)
    return {
        "workload": "in-memory-session-png-idat-v1",
        "sourceBytesPerCaseMaximum": max(
            (case["sourceReadBytesUnique"] for case in cases), default=0,
        ),
        "limits": {
            "signaturesPerPass": 4,
            "retainedSignatureWindow": 256,
            "datasetBytesMaximum": 256 * 1024 * 1024,
            "combinationsPerPass": PNGIDATFragmentReconstructor.PAIRS_PER_PASS,
            "passesMaximum": PNGIDATFragmentReconstructor.MAX_PASSES,
            "combinationsCumulativeMaximum": (
                PNGIDATFragmentReconstructor.PAIRS_PER_PASS
                * PNGIDATFragmentReconstructor.MAX_PASSES
            ),
            "readBytesPerPassMaximum": PNGIDATFragmentReconstructor.READS_PER_PASS,
            "readBytesCumulativeMaximum": (
                PNGIDATFragmentReconstructor.READS_PER_PASS
                * PNGIDATFragmentReconstructor.MAX_PASSES
            ),
            "candidateBytesMaximum": PNGIDATFragmentReconstructor.MAX_CANDIDATE_BYTES,
            "secondsPerPass": PNGIDATFragmentReconstructor.SECONDS_PER_PASS,
            "secondsCumulativeMaximum": (
                PNGIDATFragmentReconstructor.SECONDS_PER_PASS
                * PNGIDATFragmentReconstructor.MAX_PASSES
            ),
            "retainedBytesEstimateMaximum": PNGIDATFragmentReconstructor.RETAINED_BYTES,
        },
        "memoryMeasurement": "tracemalloc peak and session-accounted retained/checkpoint estimates; not process RSS",
        "cases": cases,
        "resourceMeasurements": measurements,
    }
