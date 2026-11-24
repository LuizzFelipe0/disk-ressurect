"""Compatibility exports for the split NTFS artifact-source modules."""

from infrastructure.filesystems.ntfs.artifacts.models import ArtifactScanResult, FileReference, NTFSArtifact, has_path_component
from infrastructure.filesystems.ntfs.artifacts.recycle_bin import RecycleBinAssociation, RecycleBinIndexParser, RecycleBinRecoveryHelper
from infrastructure.filesystems.ntfs.artifacts.usn_journal import UsnJournalEvidence, UsnJournalEvidenceScanner, UsnJournalParser

__all__ = [
    "ArtifactScanResult", "FileReference", "NTFSArtifact", "has_path_component",
    "RecycleBinAssociation", "RecycleBinIndexParser", "RecycleBinRecoveryHelper",
    "UsnJournalEvidence", "UsnJournalEvidenceScanner", "UsnJournalParser",
]
