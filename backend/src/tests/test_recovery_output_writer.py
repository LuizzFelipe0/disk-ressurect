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
            with patch("ntfs.recovery_output_writer.set_pkexec_user_ownership") as set_owner:
                destination, temporary_path = writer.prepare_target(output_dir, "nested/report.pdf")

        self.assertEqual(destination, os.path.join(output_dir, "nested", "report.pdf"))
        self.assertEqual(temporary_path, destination + ".partial")
        set_owner.assert_called_once_with(os.path.join(output_dir, "nested"))

    def test_temporary_files_are_unique_and_owned_before_publishing(self):
        writer = RecoveryOutputWriter()
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as output_dir:
            template = os.path.join(output_dir, "report.pdf.partial")
            with patch("ntfs.recovery_output_writer.set_pkexec_user_ownership") as set_owner:
                first_stream, first_path = writer.open_temporary(template)
                second_stream, second_path = writer.open_temporary(template)
                first_stream.close()
                second_stream.close()
                writer.prepare_file_for_publish(first_path)

                self.assertNotEqual(first_path, second_path)
                self.assertTrue(os.path.basename(first_path).startswith("report.pdf.partial."))
                set_owner.assert_called_once_with(first_path)
                writer.discard(first_path)
                writer.discard(second_path)


if __name__ == "__main__":
    unittest.main()
