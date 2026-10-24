import contextlib
import io
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from disk.scanner import DiskScanner


class FakeDisk:
    def __init__(self, data, base_offset=0):
        self.data = data
        self.base_offset = base_offset

    def read_at(self, offset, size):
        start = offset - self.base_offset
        if start < 0:
            return b""
        return self.data[start:start + size]


def make_mft_record(mft_lcn):
    record = bytearray(1024)
    record[:4] = b"FILE"
    attr_offset = 0x38
    struct.pack_into("<H", record, 20, attr_offset)
    struct.pack_into("<I", record, attr_offset, 0x80)
    struct.pack_into("<I", record, attr_offset + 4, 64)
    struct.pack_into("<H", record, attr_offset + 32, 56)
    record[attr_offset + 56:attr_offset + 60] = bytes((0x11, 1, mft_lcn, 0))
    return bytes(record)


class DiskScannerTests(unittest.TestCase):
    def test_discovers_volume_start_from_mft_runlist(self):
        mft_physical_offset = 0xC6500000
        mft_lcn = 2
        scanner = DiskScanner(FakeDisk(make_mft_record(mft_lcn), mft_physical_offset))

        with contextlib.redirect_stdout(io.StringIO()):
            volume_start = scanner.discover_via_mft_record(mft_physical_offset)

        self.assertEqual(volume_start, mft_physical_offset - mft_lcn * scanner.cluster_size)

    def test_returns_none_when_record_is_not_an_mft_record(self):
        physical_offset = 0xC6500000
        scanner = DiskScanner(FakeDisk(b"NOPE" + bytes(1020), physical_offset))

        with contextlib.redirect_stdout(io.StringIO()):
            volume_start = scanner.discover_via_mft_record(physical_offset)

        self.assertIsNone(volume_start)


if __name__ == "__main__":
    unittest.main()
