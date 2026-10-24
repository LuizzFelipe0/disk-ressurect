import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "."))

from disk.raw_disk import RawDisk
from disk.scanner import DiskScanner
from disk.mft_carver import GhostMFTCarver
from ntfs.tree_builder import TreeBuilder
from ntfs.extractor import Extractor
from reports.report_generator import ReportGenerator
from utils.progress import format_duration

# --- CONFIG ---
DISK_NUM = 2
OUTPUT_DIR = os.environ.get("DISK_RESURRECT_OUTPUT_DIR", r"D:\HD Interno")
MFT_FRAGS = [
    {"phys": 0xC6500000, "count": 113664, "base_idx": 0},
    {"phys": 0xfce823000, "count": 500000, "base_idx": 113664}
]

def main():
    started = time.perf_counter()
    print("=" * 50 + "\n DISK-RESSURECT DATA RECOVERY \n" + "=" * 50)
    disk = RawDisk(DISK_NUM)
    try:
        # 1. Scanner
        scanner = DiskScanner(disk)
        vol_start = scanner.discover_via_mft_record(MFT_FRAGS[0]['phys'])
        if not vol_start:
            print("[!] Failed to find VOL_START")
            return

        # 2. Ghost MFT scan; retained baseline behavior for this comparison run.
        ghost_records = GhostMFTCarver(disk).hunt(0, 25 * 1024 * 1024 * 1024)
        ghost_records = {}

        # 3. Build VFS with batched physical reads.
        builder = TreeBuilder(disk, MFT_FRAGS, MFT_FRAGS[0]['phys'])
        vfs = builder.build()
        builder.inject_ghosts(ghost_records)

        # 4. Extract with the original GitHub filters and single-pass logic.
        extractor = Extractor(disk, vfs, vol_start)
        extractor.set_filters(
            exts=['.jpg', '.jpeg', '.pdf', '.mp4'],
            dirs=['windows', 'program files', 'bkp fotos notebook'],
            min_kb=5
        )
        success_count = extractor.extract(OUTPUT_DIR)

        # 5. Report
        ReportGenerator.generate(vfs, OUTPUT_DIR, success_count)
        print(f"\n[+] Done! {success_count} files successfully recovered.")
        return success_count
    finally:
        disk.close()
        print(f"[*] [Run] Total elapsed: {format_duration(time.perf_counter() - started)}")

if __name__ == "__main__":
    main()