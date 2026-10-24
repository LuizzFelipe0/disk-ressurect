import os

class ReportGenerator:
    """Generates an extraction log report."""
    @staticmethod
    def generate(vfs_nodes, output_dir, extracted_count):
        print("[*] [Report] Generating recovery report...")
        os.makedirs(output_dir, exist_ok=True)
        report_path = os.path.join(output_dir, "Recovery_Report.txt")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("=== DISK RESSURECT REPORT ===\n")
            f.write(f"Total Files Extracted: {extracted_count}\n")
            f.write("============================\n\n")
            f.write("FILES FOUND IN VFS (Including skipped/corrupted):\n")

            for node in vfs_nodes.values():
                if not node.record.is_dir:
                    status = "[DELETED]" if not node.record.is_allocated else "[ACTIVE]"
                    f.write(f"{status} {node.full_path} - {node.record.file_size // 1024} KB\n")