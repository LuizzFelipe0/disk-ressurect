from ntfs.mft_parser import MFTRecord

class DiskScanner:
    """Discovers partition offsets (VOL_START) using various techniques."""
    def __init__(self, disk, cluster_size=4096):
        self.disk = disk
        self.cluster_size = cluster_size

    def discover_via_mft_record(self, mft_phys):
        """Calculates VOL_START by reading the $MFT runlist."""
        print(f"[*] [Scanner] Analyzing $MFT at {hex(mft_phys)}...")
        raw = self.disk.read_at(mft_phys, 1024)
        record = MFTRecord(raw, 0)
        if not record.is_valid or not record.data_runs:
            return None
        first_lcn, _ = record.data_runs[0]
        if first_lcn is None:
            return None
        return mft_phys - first_lcn * self.cluster_size
