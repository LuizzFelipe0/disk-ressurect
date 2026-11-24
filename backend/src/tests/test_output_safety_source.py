import os
import stat
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from infrastructure.disk.output_safety import OutputSafetyGuard
from modules.storage.entities import StorageSource


class OutputSafetySourceTests(unittest.TestCase):
    def test_raw_image_destination_on_same_filesystem_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            image = os.path.join(directory, "disk.img")
            output = os.path.join(directory, "recovered")
            with open(image, "wb") as stream:
                stream.write(b"image")
            os.mkdir(output)
            source = StorageSource("image-id", "raw_image", "disk.img", 5, 512, image)

            with self.assertRaisesRegex(ValueError, "same filesystem"):
                OutputSafetyGuard().validate_source(output, source)

    def test_raw_image_destination_on_other_filesystem_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            image = os.path.join(directory, "disk.img")
            output = os.path.join(directory, "recovered")
            with open(image, "wb") as stream:
                stream.write(b"image")
            os.mkdir(output)
            source = StorageSource("image-id", "raw_image", "disk.img", 5, 512, image)
            real_stat = os.stat

            def stat_with_other_output_device(path, *args, **kwargs):
                result = real_stat(path, *args, **kwargs)
                if os.fspath(path) == output:
                    return SimpleNamespace(
                        st_mode=stat.S_IFDIR | stat.S_IMODE(result.st_mode),
                        st_dev=result.st_dev + 1,
                    )
                if os.fspath(path) == image:
                    return SimpleNamespace(
                        st_mode=stat.S_IFREG | stat.S_IMODE(result.st_mode),
                        st_dev=result.st_dev,
                    )
                return result

            with patch("infrastructure.disk.output_safety.os.stat", side_effect=stat_with_other_output_device):
                self.assertTrue(OutputSafetyGuard().validate_source(output, source))


if __name__ == "__main__":
    unittest.main()
