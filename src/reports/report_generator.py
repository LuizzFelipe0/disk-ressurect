import os
from collections import Counter, defaultdict

class ReportGenerator:
    """Generates an extraction log report."""
    @staticmethod
    def generate(vfs_nodes, output_dir, extracted_count, extraction_results=None):
        os.makedirs(output_dir, exist_ok=True)
        report_path = os.path.join(output_dir, "Recovery_Report.txt")
        
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("=== DISK RESSURECT REPORT ===\n")
            f.write(f"Total Files Extracted: {extracted_count}\n")
            if extraction_results is not None:
                by_status = Counter(result.status for result in extraction_results)
                by_extension = defaultdict(Counter)
                for result in extraction_results:
                    by_extension[result.extension or "[no extension]"][result.status] += 1
                f.write(f"Extraction Candidates: {len(extraction_results)}\n")
                f.write("Extraction Statuses:\n")
                for status, count in sorted(by_status.items()):
                    f.write(f"  {status}: {count}\n")
                f.write("Extraction Status by Extension:\n")
                for extension, statuses in sorted(by_extension.items()):
                    summary = ", ".join(f"{status}={count}" for status, count in sorted(statuses.items()))
                    f.write(f"  {extension}: {summary}\n")
                f.write("Files Not Recovered (with reason):\n")
                for result in extraction_results:
                    if result.status != "recovered":
                        f.write(f"  [{result.status}] {result.path} - {result.reason}\n")
            f.write("============================\n\n")
            f.write("FILES FOUND IN VFS (Including skipped/corrupted):\n")
            
            for node in vfs_nodes.values():
                if not node.record.is_dir:
                    status = "[DELETED]" if not node.record.is_allocated else "[ACTIVE]"
                    f.write(f"{status} {node.full_path} - {node.record.file_size // 1024} KB\n")
