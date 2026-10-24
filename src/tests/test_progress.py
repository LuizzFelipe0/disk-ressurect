import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.progress import Progress, format_duration


class ProgressTests(unittest.TestCase):
    def test_reports_percent_elapsed_and_eta(self):
        output = io.StringIO()
        progress = Progress("Test", 4, width=10, stream=output)
        progress.update(2)
        progress.update(4)
        rendered = output.getvalue()
        self.assertIn("50%", rendered)
        self.assertIn("100%", rendered)
        self.assertIn("elapsed", rendered)
        self.assertIn("ETA", rendered)

    def test_formats_total_elapsed(self):
        self.assertEqual(format_duration(3661), "01:01:01")


if __name__ == "__main__":
    unittest.main()
