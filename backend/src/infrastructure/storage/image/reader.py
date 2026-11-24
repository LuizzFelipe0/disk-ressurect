from __future__ import annotations

import os
import stat
import threading

from modules.storage.entities import StorageSource


class RawImageReader:
    """Read a raw disk image without ever opening it for writing."""

    def __init__(self, path, bytes_per_sector=512):
        if int(bytes_per_sector) <= 0:
            raise ValueError("Image sector size must be positive")

        self.path = os.path.abspath(os.fspath(path))
        if os.path.islink(self.path):
            raise OSError("Raw disk image cannot be a symbolic link")
        self.bytes_per_sector = int(bytes_per_sector)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        self._fd = os.open(self.path, flags)
        self._read_lock = threading.Lock()
        self._closed = False
        try:
            metadata = os.fstat(self._fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("Raw disk image must be a regular file")
            self.size_bytes = int(metadata.st_size)
            self.size = self.size_bytes
            self._identity_parts = self._identity_from_stat(metadata)
            self.source = StorageSource(
                source_id=self._source_id(self._identity_parts),
                source_type="raw_image",
                display_name=os.path.basename(self.path) or self.path,
                size_bytes=self.size_bytes,
                bytes_per_sector=self.bytes_per_sector,
                locator=self.path,
            )
        except Exception:
            os.close(self._fd)
            self._closed = True
            raise

    @staticmethod
    def _identity_from_stat(metadata):
        file_id = (int(metadata.st_dev), int(metadata.st_ino))
        modified_ns = getattr(metadata, "st_mtime_ns", None)
        if modified_ns is None:
            modified_ns = int(metadata.st_mtime * 1_000_000_000)
        return (*file_id, int(metadata.st_size), int(modified_ns))

    @staticmethod
    def _source_id(identity_parts):
        return "raw-image:" + ":".join(f"{part:x}" for part in identity_parts)

    def read_at(self, offset, size):
        offset = int(offset)
        size = int(size)
        if offset < 0 or size < 0:
            raise ValueError("Image offsets and read sizes must be non-negative")
        if self._closed:
            raise OSError("Raw disk image is closed")
        if size == 0 or offset >= self.size_bytes:
            return b""

        requested = min(size, self.size_bytes - offset)
        with self._read_lock:
            os.lseek(self._fd, offset, os.SEEK_SET)
            return os.read(self._fd, requested)

    def validate_source(self):
        """Detect source replacement or modification using the open file identity."""
        if self._closed:
            raise OSError("Raw disk image is closed")
        current = self._identity_from_stat(os.fstat(self._fd))
        if current != self._identity_parts:
            raise OSError("Raw disk image changed after it was opened")
        return self.source.source_id

    def is_same_file(self, path):
        """Compare an existing path by file identity, including hard links."""
        try:
            return self._identity_from_stat(os.stat(path))[:2] == self._identity_parts[:2]
        except (OSError, TypeError, ValueError):
            return False

    def close(self):
        if not self._closed:
            os.close(self._fd)
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
