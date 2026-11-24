import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC_ROOT))

from modules.recovery.entities import (
    ContentReference,
    RecoveryCandidate,
    RecoveryEvidence,
    stable_candidate_id,
)


class RecoveryCandidateTests(unittest.TestCase):
    def test_identity_is_semantic_and_independent_of_discovery_strategy(self):
        identity = stable_candidate_id("source-a", "volume-a", "docs/report.pdf", 12)
        same_candidate = stable_candidate_id("source-a", "volume-a", "DOCS/REPORT.PDF", 12)

        self.assertEqual(identity, same_candidate)
        self.assertNotEqual(identity, stable_candidate_id("source-b", "volume-a", "docs/report.pdf", 12))
        self.assertNotEqual(identity, stable_candidate_id("source-a", "volume-b", "docs/report.pdf", 12))

    def test_candidates_without_paths_use_content_digest_not_physical_offset(self):
        digest = "a" * 64
        first = stable_candidate_id("image-1", "volume-1", None, 45, digest)
        second = stable_candidate_id("image-1", "volume-1", None, 45, digest)

        self.assertEqual(first, second)
        self.assertNotEqual(first, stable_candidate_id("image-1", "volume-1", None, 46, digest))

    def test_candidate_tracks_distinct_recovery_dimensions_and_opaque_content(self):
        reference = ContentReference("ref-session-1", "source-1", 45, "b" * 64)
        candidate = RecoveryCandidate(
            candidate_id="candidate-1",
            source_id="source-1",
            volume_id="volume-1",
            name="recovered.jpg",
            original_path=None,
            size_bytes=45,
            filesystem_id="synthetic",
            discovery_methods=("synthetic-test",),
            evidence=(RecoveryEvidence("signature", "test-adapter"),),
            deletion_state="unknown",
            allocation_state="unknown",
            integrity_state="validated",
            recoverability="recoverable",
            content_reference=reference,
        )

        self.assertEqual(candidate.content_reference, reference)
        self.assertFalse(hasattr(reference, "offset"))
        self.assertEqual(candidate.deletion_state, "unknown")
        self.assertEqual(candidate.integrity_state, "validated")

    def test_rejects_a_reference_from_another_storage_source(self):
        with self.assertRaisesRegex(ValueError, "different source"):
            RecoveryCandidate(
                candidate_id="candidate-1",
                source_id="source-1",
                volume_id="volume-1",
                name="file.bin",
                original_path=None,
                size_bytes=3,
                filesystem_id=None,
                discovery_methods=("test",),
                evidence=(),
                content_reference=ContentReference("ref", "source-2", 3),
            )


if __name__ == "__main__":
    unittest.main()
