import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ntfs.recovery_output_writer import RecoveryOutputWriter


class RecoveryOutputWriterTests(unittest.TestCase):
    def test_write_chunk_rejects_short_output_writes(self):
        class ShortWriter:
            def write(self, data):
                return len(data) - 1

        with self.assertRaisesRegex(OSError, "Short output write"):
            RecoveryOutputWriter.write_chunk(ShortWriter(), b"payload")

    def test_created_recovery_folders_are_returned_to_the_pkexec_user(self):
        writer = RecoveryOutputWriter()
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as output_dir:
            with patch("ntfs.recovery_output_writer.ensure_pkexec_user_owned_directory") as ensure_directory:
                destination, temporary_path = writer.prepare_target(output_dir, "nested/report.pdf")

        self.assertEqual(destination, os.path.join(output_dir, "nested", "report.pdf"))
        self.assertEqual(temporary_path, destination + ".partial")
        ensure_directory.assert_called_once_with(os.path.join(output_dir, "nested"))

    def test_temporary_files_are_unique_and_owned_before_publishing(self):
        writer = RecoveryOutputWriter()
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as output_dir:
            template = os.path.join(output_dir, "report.pdf.partial")
            with patch("ntfs.recovery_output_writer.set_pkexec_user_ownership_fd") as set_owner:
                first_stream, first_path = writer.open_temporary(template)
                second_stream, second_path = writer.open_temporary(template)
                first_stream.close()
                second_stream.close()

                self.assertNotEqual(first_path, second_path)
                self.assertTrue(os.path.basename(first_path).startswith("report.pdf.partial."))
                self.assertEqual(set_owner.call_count, 2)
                self.assertTrue(all(call.args[0] >= 0 for call in set_owner.call_args_list))
                writer.discard(first_path)
                writer.discard(second_path)

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux symlink protections")
    def test_output_parent_symlinks_are_rejected_before_creating_descendants(self):
        writer = RecoveryOutputWriter()
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            output_root = os.path.join(directory, "output")
            outside_root = os.path.join(directory, "outside")
            os.mkdir(output_root)
            os.mkdir(outside_root)
            os.symlink(outside_root, os.path.join(output_root, "redirect"))

            with self.assertRaisesRegex(ValueError, "unsafe or inaccessible"):
                writer.prepare_target(output_root, "redirect/created/report.pdf")

            self.assertFalse(os.path.exists(os.path.join(outside_root, "created")))


if __name__ == "__main__":
    unittest.main()
