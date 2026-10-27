import os
import struct
import sys

from disk.linux_devices import LinuxBlockDeviceCatalog


class LinuxDiskReader:
    """Read a Linux block device at byte offsets using read-only positional I/O."""

    def __init__(self, disk_number, catalog=None):
        if not sys.platform.startswith("linux"):
            raise OSError("Linux physical disk reads are only available on Linux")
        self.catalog = catalog if catalog is not None else LinuxBlockDeviceCatalog()
        self.device = self.catalog.get_device(int(disk_number))
        self.path = os.path.join(self.catalog.device_path, self.device.name)
        self.bytes_per_sector = self.device.logical_sector_size
        self.size = self.device.size_bytes
        self._closed = False
        try:
            self._fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        except PermissionError as exc:
            raise PermissionError(
                f"Permission denied reading {self.path}; authorize disk access or run the recovery service with elevated privileges"
            ) from exc
        try:
            self.size = self._read_device_size()
            self.bytes_per_sector = self._read_sector_size()
        except Exception:
            os.close(self._fd)
            self._closed = True
            raise

    def _ioctl_integer(self, request, size):
        import fcntl

        buffer = bytearray(size)
        fcntl.ioctl(self._fd, request, buffer, True)
        return struct.unpack("=Q" if size == 8 else "=I", buffer)[0]

    def _read_device_size(self):
        try:
            return self._ioctl_integer(0x80081272, 8)  # BLKGETSIZE64
        except OSError:
            if self.size > 0:
                return self.size
            raise

    def _read_sector_size(self):
        try:
            value = self._ioctl_integer(0x1268, 4)  # BLKSSZGET
        except OSError:
            value = self.bytes_per_sector
        if value <= 0:
            raise OSError(f"Linux block device {self.path} reported an invalid sector size")
        return value

    def read_at(self, offset, size):
        if offset < 0 or size < 0:
            raise ValueError("Disk offsets and read sizes must be non-negative")
        if self._closed:
            raise OSError("Physical disk handle is closed")
        if size == 0 or offset >= self.size:
            return b""
        requested = min(size, self.size - offset)
        try:
            return os.pread(self._fd, requested, offset)
        except OSError as exc:
            raise OSError(f"Could not read {requested} bytes at offset {offset} from {self.path}: {exc}") from exc

    def close(self):
        if not self._closed:
            os.close(self._fd)
            self._closed = True
