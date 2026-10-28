import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend_orchestrator import cache_path_for_data_directory, create_handler


class BackendCachePathTests(unittest.TestCase):
    def test_data_directory_is_used_for_persistent_deep_scan_cache(self):
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            handler = create_handler(cache_path=directory)

        self.assertEqual(
            os.path.basename(handler.disk_discovery.scan_repository.path),
            "deep_scan_cache.json",
        )

    def test_environment_data_directory_is_stable_across_handler_restarts(self):
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            with patch.dict(os.environ, {"DISK_RESURRECT_DATA_DIR": directory}):
                first = cache_path_for_data_directory()
                second = cache_path_for_data_directory()

        self.assertEqual(first, second)
        self.assertEqual(os.path.dirname(first), directory)


if __name__ == "__main__":
    unittest.main()
