"""File-backed and in-memory implementations of the existing read_at contract."""

from __future__ import annotations

from pathlib import Path
import threading


class FileReader:
    def __init__(self, path):
        self.path = Path(path)
        self.size = self.path.stat().st_size
        self.size_bytes = self.size
        self.bytes_per_sector = 512
        self._file = self.path.open("rb")
        self._lock = threading.Lock()

    def read_at(self, offset, size):
        offset, size = int(offset), int(size)
        if offset < 0 or size < 0 or offset + size > self.size:
            raise ValueError("Read is outside the synthetic source")
        with self._lock:
            self._file.seek(offset)
            return self._file.read(size)

    def close(self):
        self._file.close()


class MemoryReader:
    def __init__(self, data):
        self.data = bytearray(data)
        self.size = len(self.data)
        self.size_bytes = self.size
        self.bytes_per_sector = 512

    def read_at(self, offset, size):
        offset, size = int(offset), int(size)
        if offset < 0 or size < 0 or offset + size > self.size:
            raise ValueError("Read is outside the synthetic source")
        return bytes(self.data[offset:offset + size])
