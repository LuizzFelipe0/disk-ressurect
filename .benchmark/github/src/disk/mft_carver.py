import struct
from ntfs.mft_parser import MFTRecord
from utils.progress import Progress

class GhostMFTCarver:
    """Scans the disk for orphaned MFT records to rescue fragmented files."""
    def __init__(self, disk):
        self.disk = disk
        self.mft_sig = b"FILE"

    def hunt(self, start_phys, end_phys):
        print("[*] [GhostCarver] Hunting for orphaned MFT records...")
        chunk_size = 20 * 1024 * 1024
        ghosts = {}
        current = start_phys
        progress = Progress("Ghost MFT scan", end_phys - start_phys, width=24)

        while current < end_phys:
            data = self.disk.read_at(current, chunk_size)
            pos = 0
            while True:
                pos = data.find(self.mft_sig, pos)
                if pos == -1: break

                phys_found = current + pos
                if phys_found % 512 == 0:
                    raw = data[pos : pos + 1024]
                    if len(raw) == 1024:
                        fake_id = phys_found // 1024
                        rec = MFTRecord(raw, fake_id)
                        # Only keep records with data runs (useful files)
                        if rec.is_valid and rec.name and rec.data_runs:
                            ghosts[fake_id] = rec
                pos += 4
            current += chunk_size
            progress.update(current - start_phys)
        progress.finish()
        print(f"[+] [GhostCarver] Found {len(ghosts)} ghost records.")
        return ghosts