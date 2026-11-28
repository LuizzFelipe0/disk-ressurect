"""Small tests for opt-in benchmark tooling; no large workload is generated."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

BACKEND_SRC = Path(__file__).resolve().parents[1].parent / "src"
sys.path.insert(0, str(BACKEND_SRC))

from recovery.evaluation import evaluate_carving
from recovery.ground_truth import GroundTruthEntry, GroundTruthManifest
from recovery.read_coverage import InstrumentedReader
from recovery.readers import MemoryReader
from recovery.runner import run_tier1
from recovery.session_continuation import run_session_continuation_benchmark


class BenchmarkInfrastructureTests(unittest.TestCase):
    def test_reader_reports_global_and_per_stage_overlap(self):
        reader = InstrumentedReader(MemoryReader(bytes(range(32))), size=32)
        with reader.stage("test"):
            reader.read_at(0, 16)
            reader.read_at(8, 16)

        report = reader.report()
        self.assertEqual(report["requestedBytes"], 32)
        self.assertEqual(report["successfulBytes"], 32)
        self.assertEqual(report["globalUniqueBytes"], 24)
        self.assertEqual(report["globalRepeatedBytes"], 8)
        self.assertEqual(report["stages"]["test"]["uniqueBytes"], 24)
        self.assertEqual(report["stages"]["test"]["operations"], 2)

    def test_reader_bounds_interval_accounting_and_reports_unknown_unique_bytes(self):
        reader = InstrumentedReader(MemoryReader(bytes(64)), size=64, interval_cap=1)
        reader.read_at(0, 8)
        reader.read_at(16, 8)
        report = reader.report()
        self.assertTrue(report["globalIntervalLedgerTruncated"])
        self.assertIsNone(report["globalUniqueBytes"])

    def test_reader_reports_short_reads_and_read_errors(self):
        class ShortReader(MemoryReader):
            def read_at(self, offset, size):
                return super().read_at(offset, max(0, size - 1))

        short_reader = InstrumentedReader(ShortReader(bytes(16)), size=16)
        self.assertEqual(short_reader.read_at(0, 8), bytes(7))
        short_report = short_reader.report()
        self.assertEqual(short_report["stages"]["unclassified"]["shortReads"], 1)
        self.assertEqual(short_report["successfulBytes"], 7)

        class ErrorReader(MemoryReader):
            def read_at(self, offset, size):
                raise OSError("synthetic read error")

        error_reader = InstrumentedReader(ErrorReader(bytes(16)), size=16)
        with self.assertRaisesRegex(OSError, "synthetic read error"):
            error_reader.read_at(0, 8)
        self.assertEqual(error_reader.report()["stages"]["unclassified"]["errors"], 1)

    def test_manifest_keeps_oracle_hash_outside_reader_contract(self):
        original = b"known-original"
        entry = GroundTruthEntry.original(
            "fixture-a", original, physical_ranges=((4, 18),),
        )
        manifest = GroundTruthManifest(7, "small", 32, (entry,), ((0, 32),), ())
        reader = MemoryReader(bytes(32))

        self.assertIn(entry.sha256, manifest.serialize())
        self.assertFalse(hasattr(reader, "manifest"))
        self.assertFalse(hasattr(reader, "sha256"))

    def test_evaluation_uses_oracle_afterward_and_reports_false_accepts_by_offset(self):
        good = b"known-original"
        corrupted = b"known-corrupted"
        manifest = GroundTruthManifest(
            1,
            "evaluation",
            64,
            (
                GroundTruthEntry.original("first-copy", good, physical_ranges=((4, 18),)),
                GroundTruthEntry.original("second-copy", good, physical_ranges=((20, 34),)),
                GroundTruthEntry.original(
                    "overwritten", b"old-content", physical_ranges=((40, 50),),
                    negative_reason="overwritten",
                ),
            ),
            ((0, 64),),
            (),
        )
        candidates = (
            SimpleNamespace(data=good, offset=4, extension=".bin", strategy="contiguous_carving"),
            SimpleNamespace(data=corrupted, offset=40, extension=".bin", strategy="contiguous_carving"),
        )

        result = evaluate_carving(candidates, manifest)

        self.assertEqual(result["recoveredOriginalIds"], ["first-copy"])
        self.assertEqual(result["missedOriginalIds"], ["second-copy"])
        self.assertEqual(result["uniqueOriginalContentsExpected"], 1)
        self.assertEqual(result["uniqueOriginalContentsRecovered"], 1)
        self.assertEqual(result["physicalOccurrencesExpected"], 2)
        self.assertEqual(result["physicalOccurrencesDiscovered"], 1)
        self.assertEqual(result["physicalOccurrenceMisses"], 1)
        self.assertEqual(result["duplicatePhysicalOccurrenceMisses"], 1)
        self.assertTrue(result["currentDigestDeduplicationMaySuppressPhysicalOccurrences"])
        self.assertEqual(result["falseAcceptedCandidateCount"], 1)
        self.assertEqual(result["falseAcceptedCandidates"][0]["groundTruthNegativeId"], "overwritten")

    def test_session_benchmark_recovers_complete_png_after_contiguous_miss(self):
        result = run_session_continuation_benchmark()
        control, continued = result["cases"]

        self.assertEqual(control["signatureCount"], 4)
        self.assertEqual(continued["signatureCount"], 5)
        self.assertEqual(0, continued["contiguousPngCandidates"])
        self.assertEqual(1, continued["exactOriginalMatchesAfterSearch"])
        self.assertEqual(1, continued["completeReconstructionHypotheses"])
        self.assertEqual("scope_complete", continued["scopeStopReason"])
        self.assertEqual(5, continued["uniqueSignaturesExamined"])
        self.assertEqual(64, result["limits"]["combinationsPerPass"])
        self.assertEqual(256, result["limits"]["combinationsCumulativeMaximum"])
        self.assertEqual(8 * 1024 * 1024, result["limits"]["readBytesPerPassMaximum"])
        self.assertEqual(16 * 1024 * 1024,
                         result["limits"]["retainedBytesEstimateMaximum"])
        self.assertFalse(continued["oraclePassedIntoSearch"])
        self.assertFalse(continued["oraclePositionsPassedIntoSearch"])

    def test_resume_benchmark_separates_required_candidate_restoration_reads(self):
        suite = run_tier1(seed=72531)["rangeAndResume"]
        range_page = suite["rangeCollection"]
        self.assertFalse(range_page["candidateInOmittedFreeRangeRecovered"])
        self.assertTrue(range_page["candidateRecoveredAfterBoundedContinuation"])
        self.assertEqual(range_page["continuedCandidateOffsets"], [2 * 4096])

        result = suite["boundedCheckpointResume"]

        self.assertEqual(
            result["candidateRestoreBytesReadTotal"],
            sum(item["candidateRestoreBytesRead"] for item in result["passes"]),
        )
        self.assertTrue(result["candidateRestorationReadsAreRequiredForSourceFreshness"])
        self.assertEqual(result["timingScope"], "one sequential checkpoint-resume session")


if __name__ == "__main__":
    unittest.main()
