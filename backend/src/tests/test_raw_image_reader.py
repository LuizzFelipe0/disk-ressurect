import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SRC_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC_ROOT))

from infrastructure.storage.image.reader import RawImageReader


class RawImageReaderTests(unittest.TestCase):
    def test_reads_positionally_and_clamps_at_end_of_image(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disk.img"
            path.write_bytes(b"0123456789")

            with RawImageReader(path) as reader:
                self.assertEqual(reader.size_bytes, 10)
                self.assertEqual(reader.read_at(3, 4), b"3456")
                self.assertEqual(reader.read_at(8, 8), b"89")
                self.assertEqual(reader.read_at(10, 1), b"")
                self.assertEqual(reader.read_at(0, 0), b"")
                self.assertEqual(reader.validate_source(), reader.source.source_id)

    def test_rejects_invalid_offsets_and_reads_after_close(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disk.img"
            path.write_bytes(b"image")
            reader = RawImageReader(path)

            with self.assertRaises(ValueError):
                reader.read_at(-1, 1)
            with self.assertRaises(ValueError):
                reader.read_at(0, -1)
            reader.close()
            with self.assertRaises(OSError):
                reader.read_at(0, 1)

    def test_source_identity_distinguishes_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.img"
            other = Path(directory) / "other.img"
            source.write_bytes(b"same bytes")
            other.write_bytes(b"same bytes")

            with RawImageReader(source) as reader:
                self.assertFalse(reader.is_same_file(other))

    def test_source_identity_recognizes_hard_link_file_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.img"
            source.write_bytes(b"image")
            with RawImageReader(source) as reader:
                hard_link_stat = SimpleNamespace(
                    st_dev=reader._identity_parts[0],
                    st_ino=reader._identity_parts[1],
                    st_size=reader.size_bytes,
                    st_mtime_ns=reader._identity_parts[3],
                )
                with patch("infrastructure.storage.image.reader.os.stat", return_value=hard_link_stat):
                    self.assertTrue(reader.is_same_file("hard-link-alias"))

    def test_detects_image_changes_through_the_open_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disk.img"
            path.write_bytes(b"image")
            with RawImageReader(path) as reader:
                with path.open("ab") as image:
                    image.write(b"changed")
                with self.assertRaisesRegex(OSError, "changed"):
                    reader.validate_source()

    def test_rejects_symbolic_link_paths(self):
        with patch("infrastructure.storage.image.reader.os.path.islink", return_value=True):
            with self.assertRaisesRegex(OSError, "symbolic link"):
                RawImageReader("alias.img")


if __name__ == "__main__":
    unittest.main()
