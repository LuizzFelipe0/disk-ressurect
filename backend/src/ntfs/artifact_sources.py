"""Compatibility exports for the split NTFS artifact-source modules."""

from ntfs.artifact_models import ArtifactScanResult, FileReference, NTFSArtifact, has_path_component
from ntfs.recycle_bin import RecycleBinAssociation, RecycleBinIndexParser, RecycleBinRecoveryHelper
from ntfs.usn_journal import UsnJournalEvidence, UsnJournalEvidenceScanner, UsnJournalParser

__all__ = [
    "ArtifactScanResult", "FileReference", "NTFSArtifact", "has_path_component",
    "RecycleBinAssociation", "RecycleBinIndexParser", "RecycleBinRecoveryHelper",
    "UsnJournalEvidence", "UsnJournalEvidenceScanner", "UsnJournalParser",
]
