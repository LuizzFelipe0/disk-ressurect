import struct
from ntfs.mft_parser import MFTRecord
from typing import Callable

class GhostMFTCarver:
    """Scans the disk for orphaned MFT records to rescue fragmented files."""
    def __init__(self, disk):
        self.disk = disk
        self.mft_sig = b"FILE"

    def hunt(self, start_phys, end_phys, progress_callback: Callable[[int, int], None] | None = None):
        chunk_size = 20 * 1024 * 1024
        ghosts = {}
        current = start_phys
        
        while current < end_phys:
            request_size = min(chunk_size, end_phys - current)
            data = self.disk.read_at(current, request_size)
            if not data:
                break
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
            current += request_size
            if progress_callback is not None:
                progress_callback(current - start_phys, end_phys - start_phys)
        return ghosts
