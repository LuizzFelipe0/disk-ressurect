import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "."))

from disk.raw_disk import RawDisk
from disk.scanner import DiskScanner
from disk.mft_carver import GhostMFTCarver
from ntfs.tree_builder import TreeBuilder
from ntfs.extractor import Extractor
from reports.report_generator import ReportGenerator

# --- CONFIG ---
DISK_NUM = 2
OUTPUT_DIR = r"D:\HD Interno"
MFT_FRAGS = [
    {"phys": 0xC6500000, "count": 113664, "base_idx": 0},
    {"phys": 0xfce823000, "count": 500000, "base_idx": 113664}
]

def main():
    print("=" * 50 + "\n PRO DATA RECOVERY ENGINE \n" + "=" * 50)
    disk = RawDisk(DISK_NUM)

    # 1. Scanner
    scanner = DiskScanner(disk)
    vol_start = scanner.discover_via_mft_record(MFT_FRAGS[0]['phys'])
    if not vol_start: return print("[!] Failed to find VOL_START")
    
    # 2. Ghost MFT Scan (Acha os metadados na zona destruída - 0 a 25GB)
    ghost_records = GhostMFTCarver(disk).hunt(0, 25 * 1024 * 1024 * 1024)
    ghost_records = {} 

    # 3. Build VFS
    builder = TreeBuilder(disk, MFT_FRAGS, MFT_FRAGS[0]['phys'])
    vfs = builder.build()
    builder.inject_ghosts(ghost_records)

    # 4. Extract
    extractor = Extractor(disk, vfs, vol_start)
    extractor.set_filters(
        exts=['.jpg', '.jpeg', '.pdf', '.mp4'],
        dirs=['windows', 'program files', 'bkp fotos notebook'],
        min_kb=5
    )
    success_count = extractor.extract(OUTPUT_DIR)

    # 5. Report
    ReportGenerator.generate(vfs, OUTPUT_DIR, success_count)
    
    disk.close()
    print(f"\n[+] Done! {success_count} files successfully recovered.")

if __name__ == "__main__":
    main()