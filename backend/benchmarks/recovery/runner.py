"""Opt-in Phase 5B component/workflow benchmarks for synthetic sources only."""

from __future__ import annotations

from dataclasses import asdict
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import tempfile
import time
import tracemalloc

from infrastructure.carving.content_carver import RawContentCarver
from infrastructure.carving.png_idat_fragment_reconstructor import PNGIDATFragmentReconstructor
from infrastructure.filesystems.ntfs.allocation.cluster_allocation import FreeClusterRangeCollector
from infrastructure.filesystems.ntfs.readers.file_content_reader import NTFSFileContentReader
from infrastructure.validation.disk_auditor import DiskReadCoverage
from .datasets import CLUSTER_SIZE, create_dataset
from .evaluation import evaluate_carving
from .ground_truth import GroundTruthEntry, GroundTruthManifest
from .read_coverage import InstrumentedReader
from .readers import FileReader, MemoryReader
from .resource_measurement import measure, process_memory_bytes
from .session_continuation import run_session_continuation_benchmark


def _media(seed, fmt="JPEG", progressive=False):
    from .datasets import _image_bytes
    return _image_bytes(seed, format_name=fmt, quality=88, progressive=progressive)


def _carver(source, manifest, *, measured):
    carver_source = source
    if measured:
        carver_source = (source if isinstance(source, InstrumentedReader)
                         else InstrumentedReader(source, size=source.size))
    carver = RawContentCarver(
        carver_source,
        chunk_size=1024 * 1024,
        max_scan_bytes=source.size,
        max_file_bytes=2 * 1024 * 1024,
        max_total_file_bytes=64 * 1024 * 1024,
        max_candidate_read_bytes=128 * 1024 * 1024,
        max_candidate_read_bytes_per_format=64 * 1024 * 1024,
        max_decoded_png_bytes=16 * 1024 * 1024,
        max_files=512,
    )
    stage = getattr(carver_source, "stage", None)
    stage_context = stage("content_carving") if stage else nullcontext()
    with stage_context:
        result = carver.scan(manifest.eligible_ranges, collect_png_signatures=True)
    report = evaluate_carving(result.files, manifest)
    report.update({
        "bytesScanned": result.bytes_scanned,
        "scanLimitReached": result.scan_limit_reached,
        "candidateBytesRead": result.candidate_bytes_read,
        "candidateRestoreBytesRead": result.candidate_restore_bytes_read,
        "candidateLimitReached": result.candidate_limit_reached,
        "fileCountLimitReached": result.file_count_limit_reached,
        "retainedBytesLimitReached": result.retained_bytes_limit_reached,
        "pngSignaturesRetained": len(result.png_signature_offsets),
        "pngSignatureSetTruncated": result.png_signature_set_truncated,
        "formatStats": [asdict(item) for item in result.format_stats],
    })
    if measured:
        report["readCoverage"] = carver_source.report()
    return result, report, carver_source


def _signature_coverage_case(count, *, seed):
    block_size = 8192
    data = bytearray(block_size * count)
    signature = b"\x89PNG\r\n\x1a\n"
    signature_offsets = []
    eligible_ranges = []
    for index in range(count):
        offset = index * block_size
        signature_offsets.append(offset)
        data[offset:offset + len(signature)] = signature
        fake_header = b"not-a-complete-png-candidate".ljust(48 - len(signature), b"\0")
        data[offset + len(signature):offset + 48] = fake_header
        eligible_ranges.append((offset, offset + 48))

    source = InstrumentedReader(MemoryReader(data), size=len(data), capture_events=True)
    with source.stage("content_carving"):
        scan = RawContentCarver(
            source, chunk_size=64 * 1024, max_scan_bytes=len(data),
            max_file_bytes=block_size, max_total_file_bytes=8 * 1024 * 1024,
            max_candidate_read_bytes=32 * 1024 * 1024,
            max_candidate_read_bytes_per_format=32 * 1024 * 1024,
            max_files=count + 1,
        ).scan(eligible_ranges, collect_png_signatures=True)
    with source.stage("png_fragment_reconstruction"):
        reconstruction = PNGIDATFragmentReconstructor(
            source, volume_start=0, volume_end=len(data), cluster_size=CLUSTER_SIZE,
        ).reconstruct(scan.png_signature_offsets, eligible_ranges)
    return {
        "scenario": f"{count}_png_signatures",
        "seed": seed,
        "eligibleSignatureCountInOracle": count,
        "signatureOffsetsDetectedByOracle": count,
        "signaturesRetained": len(scan.png_signature_offsets),
        "signaturesOmittedBy256CapAtLeast": max(0, count - len(scan.png_signature_offsets)),
        "signatureSetTruncated": scan.png_signature_set_truncated,
        "fragmentSearchSignaturesSeen": reconstruction.signatures_seen,
        "fragmentSearchSignaturesExamined": reconstruction.signatures_examined,
        "fragmentSearchCombinations": reconstruction.combinations,
        "fragmentSearchCandidates": len(reconstruction.candidates),
        "fragmentSearchStopReason": reconstruction.stop_reason,
        "bytesScanned": scan.bytes_scanned,
        "candidateBytesRead": scan.candidate_bytes_read,
        "readCoverage": source.report(),
        "oracle": {
            "knownSignatures": signature_offsets,
            "sha256UsedByAlgorithm": False,
            "fragmentLocationsProvidedToAlgorithm": False,
        },
    }

def _range_and_resume_experiments(seed):
    jpeg, _pixels, _geometry = _media(seed)
    cluster_count = 4
    bitmap = bytes([(1 << 1) | (1 << 3)])
    collector = FreeClusterRangeCollector(
        0, CLUSTER_SIZE, cluster_count, max_bytes=CLUSTER_SIZE * 4, max_ranges=1,
    )
    collector.consume(bitmap, 0)
    retained = collector.finish()
    small_data = bytearray(CLUSTER_SIZE * cluster_count)
    small_data[2 * CLUSTER_SIZE:2 * CLUSTER_SIZE + len(jpeg)] = jpeg
    source = InstrumentedReader(MemoryReader(small_data), size=len(small_data))
    limited = RawContentCarver(
        source, max_scan_bytes=len(small_data), max_file_bytes=64 * 1024,
        max_total_file_bytes=128 * 1024, max_candidate_read_bytes=128 * 1024,
        max_candidate_read_bytes_per_format=128 * 1024, max_files=8,
    ).scan(retained["ranges"])

    resumed_data = bytearray(128 * 1024)
    first_jpeg, *_ = _media(seed + 1)
    later_jpeg, *_ = _media(seed + 2)
    resumed_data[4096:4096 + len(first_jpeg)] = first_jpeg
    resumed_data[48 * 1024:48 * 1024 + len(later_jpeg)] = later_jpeg
    resumed_source = InstrumentedReader(MemoryReader(resumed_data), size=len(resumed_data))
    checkpoint = None
    passes = []
    for _ in range(8):
        result = RawContentCarver(
            resumed_source, chunk_size=4096, max_scan_bytes=16 * 1024,
            max_file_bytes=64 * 1024, max_total_file_bytes=256 * 1024,
            max_candidate_read_bytes=256 * 1024,
            max_candidate_read_bytes_per_format=256 * 1024, max_files=8,
        ).scan(((0, len(resumed_data)),), resume_checkpoint=checkpoint)
        passes.append({
            "bytesScanned": result.bytes_scanned,
            "cumulativeBytesScanned": result.cumulative_bytes_scanned,
            "filesFound": len(result.files),
            "scanLimitReached": result.scan_limit_reached,
            "candidateRestoreBytesRead": result.candidate_restore_bytes_read,
        })
        checkpoint = result.checkpoint
        if not result.scan_limit_reached:
            break
    return {
        "rangeCollection": {
            "allBitmapFreeRanges": [[0, CLUSTER_SIZE], [2 * CLUSTER_SIZE, 3 * CLUSTER_SIZE]],
            "retainedRanges": [list(item) for item in retained["ranges"]],
            "rangeCollectionTruncated": retained["truncated"],
            "carverCandidatesFromRetainedRange": len(limited.files),
            "candidateInOmittedFreeRangeRecovered": False,
            "readCoverage": source.report(),
        },
        "boundedCheckpointResume": {
            "passes": passes,
            "stopReason": "scope_complete" if passes and not passes[-1]["scanLimitReached"] else "budget_exhausted",
            "candidateAfterFirstWindowEventuallySeen": bool(passes and passes[-1]["filesFound"] >= 2),
            "readCoverage": resumed_source.report(),
        },
    }


def run_tier1(seed=72531):
    cases = [_signature_coverage_case(count, seed=seed + count) for count in (4, 5, 257)]
    range_results = _range_and_resume_experiments(seed)
    return {
        "tier": "1-small-deterministic",
        "seed": seed,
        "signatureCoverage": cases,
        "rangeAndResume": range_results,
        "sessionContinuation": run_session_continuation_benchmark(),
    }


def run_file_workload(size_bytes, *, seed=72531, repeats=3):
    temp_root = Path(os.environ.get("TEMP") or tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(prefix="disk-ressurect-phase5b-", dir=temp_root) as work:
        work_dir = Path(work).resolve()
        source_path = work_dir / "synthetic-source.img"
        dataset_start = time.perf_counter()
        built = create_dataset(source_path, size_bytes, seed=seed)
        dataset_seconds = time.perf_counter() - dataset_start
        file_reader = FileReader(source_path)
        instrumented = InstrumentedReader(file_reader, size=file_reader.size)
        with instrumented.stage("physical_audit"):
            audit_result, audit_metrics = measure(lambda: _scan_physical_coverage(instrumented))
        try:
            measurements = []
            uninstrumented_measurements = []
            uninstrumented_reports = []
            expected_ids = None
            last_result = last_report = None
            for _ in range(max(3, int(repeats))):
                plain_reader = FileReader(source_path)
                try:
                    plain_result, plain_metrics = measure(
                        lambda: _carver(plain_reader, built.manifest, measured=False),
                    )
                finally:
                    plain_reader.close()
                uninstrumented_measurements.append(plain_metrics)
                uninstrumented_reports.append(plain_result[1])
            for _ in range(max(3, int(repeats))):
                result, measured = measure(
                    lambda: _carver(instrumented, built.manifest, measured=True),
                )
                carve_result, report, _wrapped = result
                measurements.append(measured)
                expected_ids = report["recoveredOriginalIds"]
                last_result, last_report = carve_result, report

            with instrumented.stage("ntfs_content_read"):
                synthetic_node = type("SyntheticNode", (), {
                    "record": type("SyntheticRecord", (), {
                        "file_size": next(item.size_bytes for item in built.manifest.entries
                                           if item.file_id == "metadata-fragmented-jpeg"),
                        "data_is_complete": True,
                        "resident_data": None,
                        "data_runs": built.ntfs_runs,
                    })(),
                })()
                metadata_bytes = b"".join(NTFSFileContentReader(
                    instrumented, 0, CLUSTER_SIZE,
                    volume_size_bytes=instrumented.size,
                ).iter_chunks(synthetic_node))
            metadata_entry = next(item for item in built.manifest.entries
                                  if item.file_id == "metadata-fragmented-jpeg")
            metadata_match = hashlib.sha256(metadata_bytes).hexdigest() == metadata_entry.sha256

            signature_offsets = last_result.png_signature_offsets
            with instrumented.stage("png_fragment_reconstruction"):
                recon_result, recon_metrics = measure(lambda: PNGIDATFragmentReconstructor(
                    instrumented, volume_start=0, volume_end=instrumented.size,
                    cluster_size=CLUSTER_SIZE,
                ).reconstruct(signature_offsets, built.manifest.eligible_ranges))

            metrics = instrumented.report()
            timings = [item["wallSeconds"] for item in measurements]
            cpu_times = [item["cpuSeconds"] for item in measurements]
            plain_timings = [item["wallSeconds"] for item in uninstrumented_measurements]
            instrumented_median = statistics.median(timings)
            plain_median = statistics.median(plain_timings)
            return {
                "tier": f"file-backed-{size_bytes // (1024 * 1024)}MiB",
                "workload": built.manifest.workload,
                "seed": seed,
                "datasetConstructionSeconds": dataset_seconds,
                "datasetSha256": _file_hash(source_path),
                "datasetRemovedAfterRun": True,
                "manifest": json.loads(built.manifest.serialize()),
                "configuration": {
                    "timedRepeats": len(measurements),
                    "uninstrumentedTimingRepeats": len(uninstrumented_measurements),
                    "scanBudgetBytes": size_bytes,
                    "candidateBytes": 128 * 1024 * 1024,
                    "candidateBytesPerFormat": 64 * 1024 * 1024,
                    "maxFiles": 512,
                    "maxFileBytes": 2 * 1024 * 1024,
                    "eligibleRangeBytes": sum(end - start for start, end in built.manifest.eligible_ranges),
                    "allocationBitmap": "synthetic bitmap; not a complete NTFS filesystem image",
                },
                "contiguousCarving": {
                    **last_report,
                    "wallSeconds": {
                        "min": min(plain_timings), "median": statistics.median(plain_timings),
                        "max": max(plain_timings), "samples": plain_timings,
                    },
                    "cpuSeconds": {
                        "min": min(item["cpuSeconds"] for item in uninstrumented_measurements),
                        "median": statistics.median(item["cpuSeconds"] for item in uninstrumented_measurements),
                        "max": max(item["cpuSeconds"] for item in uninstrumented_measurements),
                        "samples": [item["cpuSeconds"] for item in uninstrumented_measurements],
                    },
                    "timingSource": "plain positional FileReader; instrumentation excluded",
                    "throughput": {
                        "scannedBytesPerSecond": last_result.bytes_scanned / statistics.median(plain_timings),
                        "scannedMiBPerSecond": (last_result.bytes_scanned / (1024 * 1024))
                        / statistics.median(plain_timings),
                        "scope": "eligible synthetic source bytes scanned; file-backed C: run, not physical-HDD throughput",
                    },
                    "repeatReadCoverage": metrics,
                    "instrumentationOverhead": {
                        "plainWallSeconds": {"min": min(plain_timings), "median": plain_median,
                                             "max": max(plain_timings), "samples": plain_timings},
                        "measuredWallSeconds": {"min": min(timings), "median": instrumented_median,
                                                "max": max(timings), "samples": timings},
                        "medianRelativeChange": (instrumented_median / plain_median - 1)
                        if plain_median else None,
                        "measurementIncludesTracemallocForBothPaths": True,
                        "instrumentedTimingUsedForThroughput": False,
                    },
                    "instrumentedTiming": {
                        "wallSeconds": {
                            "min": min(timings), "median": statistics.median(timings),
                            "max": max(timings), "samples": timings,
                        },
                        "cpuSeconds": {
                            "min": min(cpu_times), "median": statistics.median(cpu_times),
                            "max": max(cpu_times), "samples": cpu_times,
                        },
                    },
                    "instrumentationNote": "Instrumented samples include stack classification and bounded interval accounting; compare against the plain reader before interpreting throughput.",
                    "uninstrumentedTiming": {
                        "wallSeconds": {
                            "min": min(item["wallSeconds"] for item in uninstrumented_measurements),
                            "median": statistics.median(item["wallSeconds"] for item in uninstrumented_measurements),
                            "max": max(item["wallSeconds"] for item in uninstrumented_measurements),
                            "samples": [item["wallSeconds"] for item in uninstrumented_measurements],
                        },
                        "cpuSeconds": {
                            "min": min(item["cpuSeconds"] for item in uninstrumented_measurements),
                            "median": statistics.median(item["cpuSeconds"] for item in uninstrumented_measurements),
                            "max": max(item["cpuSeconds"] for item in uninstrumented_measurements),
                            "samples": [item["cpuSeconds"] for item in uninstrumented_measurements],
                        },
                        "pythonAllocationPeakBytes": [item["tracemallocPeakBytes"] for item in uninstrumented_measurements],
                    },
                    "plainAndInstrumentedResultsEquivalent": all(
                        item["recoveredOriginalIds"] == last_report["recoveredOriginalIds"]
                        and item["candidateCount"] == last_report["candidateCount"]
                        and item["falseAcceptedCandidateCount"] == last_report["falseAcceptedCandidateCount"]
                        for item in uninstrumented_reports
                    ),
                },
                "physicalAuditCoverageComponent": {
                    "uniqueBytes": audit_result.bytes_read,
                    "readBytes": audit_result.bytes_read_total,
                    "issues": len(audit_result.issues),
                    "wallSeconds": audit_metrics["wallSeconds"],
                    "cpuSeconds": audit_metrics["cpuSeconds"],
                    "scope": "DiskReadCoverage full-range scanner only; not a complete partition/NTFS audit",
                },
                "pngFragmentReconstruction": {
                    "candidates": len(recon_result.candidates),
                    "signaturesSeen": recon_result.signatures_seen,
                    "signaturesExamined": recon_result.signatures_examined,
                    "combinations": recon_result.combinations,
                    "bytesRead": recon_result.bytes_read,
                    "stopReason": recon_result.stop_reason,
                    "wallSeconds": recon_metrics["wallSeconds"],
                    "cpuSeconds": recon_metrics["cpuSeconds"],
                    "scope": "production component run on the file-backed synthetic source",
                },
                "ntfsRunlistComponent": {
                    "status": "exact" if metadata_match else "mismatch",
                    "sha256MatchesOracle": metadata_match,
                    "bytesRead": len(metadata_bytes),
                    "fullWorkflow": False,
                },
                "processMemory": process_memory_bytes(),
                "pythonAllocationMeasurement": "tracemalloc peaks are in repeat samples; does not include process RSS",
                "mediaFilesAreDecodable": True,
                "mediaDecodeValidation": "Pillow reopened and fully decoded each generated PNG/JPEG before placement; no external media files were used",
                "recoveredOriginalIds": expected_ids,
            }
        finally:
            file_reader.close()


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _scan_physical_coverage(reader):
    coverage = DiskReadCoverage(reader)
    coverage.scan_full_disk()
    return coverage


def run_benchmarks(tier, *, size_mib=64, seed=72531):
    result = {
        "schemaVersion": 1,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processMemory": process_memory_bytes(),
        },
        "tier1": run_tier1(seed),
    }
    if tier in {"64", "256"}:
        size = int(size_mib) * 1024 * 1024
        if size_mib not in (64, 256):
            raise ValueError("Only the approved 64 MiB and conditional 256 MiB tiers are implemented")
        result["fileWorkload"] = run_file_workload(size, seed=seed)
    return result
