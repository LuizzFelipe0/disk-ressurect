from dataclasses import dataclass

from disk.models import NTFSVolume
from domain.recovery_catalog import RecoveryCatalog


@dataclass(frozen=True)
class RecoveryCatalogSnapshot:
    catalog: RecoveryCatalog
    volume: NTFSVolume
    orphan_scan_performed: bool = False
    content_carving_summary: dict | None = None
    parent_reference_issue_count: int = 0
    low_confidence_carving_summary: dict | None = None
    recycle_bin_summary: dict | None = None
    usn_journal_summary: dict | None = None
    ntfs_log_file_summary: dict | None = None

    @property
    def volume_start(self):
        return self.volume.partition_offset

    @property
    def cluster_size(self):
        return self.volume.cluster_size
