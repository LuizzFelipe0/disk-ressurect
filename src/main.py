import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "."))

from disk.raw_disk import RawDisk
from disk.scanner import DiskScanner
from disk.output_safety import OutputSafetyGuard
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
    output_disks = OutputSafetyGuard().validate(OUTPUT_DIR, DISK_NUM)
    print(f"[*] [Safety] Recovery output uses physical disk(s): {output_disks}")
    disk = RawDisk(DISK_NUM)
    try:
        # 1. Scanner
        scanner = DiskScanner(disk)
        vol_start = scanner.discover_via_mft_record(MFT_FRAGS[0]['phys'])
        if not vol_start:
            print("[!] Failed to find VOL_START")
            return

        # 2. Build the catalog from the primary MFT. Orphan-record scanning is
        # intentionally deferred until it can feed the same selectable tree.
        builder = TreeBuilder(disk, MFT_FRAGS, MFT_FRAGS[0]['phys'])
        vfs = builder.build()

        # 3. Extract photos, videos and common Office documents.
        extractor = Extractor(disk, vfs, vol_start)
        extractor.set_filters(
            exts=[
                '.jpg', '.jpeg', '.png', '.mp4',
                '.pdf', '.doc', '.docx', '.docm', '.rtf',
                '.xls', '.xlsx', '.xlsm',
            ],
            dirs=['windows', 'program files', 'bkp fotos notebook'],
            min_kb=5
        )
        success_count = extractor.extract(OUTPUT_DIR)

        # 4. Report
        ReportGenerator.generate(vfs, OUTPUT_DIR, success_count, extractor.results)
        print(f"\n[+] Done! {success_count} files successfully recovered.")
        return success_count
    finally:
        disk.close()
        print(f"[*] [Run] Total elapsed: {format_duration(time.perf_counter() - started)}")

if __name__ == "__main__":
    main()
