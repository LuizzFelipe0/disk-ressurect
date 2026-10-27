import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from reports.report_generator import ReportGenerator


class ReportGeneratorTests(unittest.TestCase):
    def test_report_includes_status_summary_and_failure_reasons(self):
        good_node = SimpleNamespace(full_path="photos\\good.jpg", record=SimpleNamespace(name="good.jpg"))
        bad_node = SimpleNamespace(full_path="docs\\broken.xlsx", record=SimpleNamespace(name="broken.xlsx"))
        results = [
            SimpleNamespace(node=good_node, status="recovered", reason="complete", bytes_written=10,
                            path=good_node.full_path, extension=".jpg"),
            SimpleNamespace(node=bad_node, status="invalid_container", reason="missing workbook", bytes_written=12,
                            path=bad_node.full_path, extension=".xlsx"),
        ]
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with tempfile.TemporaryDirectory(dir=repo_root) as output_dir:
            ReportGenerator.generate({}, output_dir, 1, results)
            with open(os.path.join(output_dir, "Recovery_Report.txt"), encoding="utf-8") as report:
                content = report.read()

        self.assertIn("Extraction Candidates: 2", content)
        self.assertIn("invalid_container: 1", content)
        self.assertIn(".xlsx: invalid_container=1", content)
        self.assertIn("[invalid_container] docs\\broken.xlsx - missing workbook", content)


if __name__ == "__main__":
    unittest.main()
