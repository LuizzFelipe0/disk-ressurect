import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ntfs.recovery_output_writer import RecoveryOutputWriter


class RecoveryOutputWriterTests(unittest.TestCase):
    def test_write_chunk_rejects_short_output_writes(self):
        class ShortWriter:
            def write(self, data):
                return len(data) - 1

        with self.assertRaisesRegex(OSError, "Short output write"):
            RecoveryOutputWriter.write_chunk(ShortWriter(), b"payload")


if __name__ == "__main__":
    unittest.main()
