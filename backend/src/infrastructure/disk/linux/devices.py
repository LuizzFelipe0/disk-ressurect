import os
from dataclasses import dataclass


_PSEUDO_DEVICE_PREFIXES = ("loop", "ram", "zram", "dm-", "md", "fd", "sr")


@dataclass(frozen=True)
class LinuxBlockDevice:
    number: int
    name: str
    model: str
    size_bytes: int
    serial_number: str
    logical_sector_size: int


class LinuxBlockDeviceCatalog:
    """Maps stable sysfs block-device names to the application's disk numbers."""

    def __init__(self, sys_block_path="/sys/block", device_path="/dev"):
        self.sys_block_path = sys_block_path
        self.device_path = device_path

    def list_devices(self):
        try:
            names = sorted(os.listdir(self.sys_block_path))
        except OSError as exc:
            raise OSError(f"Could not enumerate Linux block devices in {self.sys_block_path}: {exc}") from exc

        devices = []
        for name in names:
            if name.startswith(_PSEUDO_DEVICE_PREFIXES):
                continue
            root = os.path.join(self.sys_block_path, name)
            size_sectors = self._read_integer(os.path.join(root, "size"), default=0)
            size_bytes = size_sectors * 512
            if size_bytes <= 0:
                continue
            model = self._read_text(os.path.join(root, "device", "model"))
            vendor = self._read_text(os.path.join(root, "device", "vendor"))
            serial = self._read_text(os.path.join(root, "device", "serial"))
            logical_sector_size = self._read_integer(
                os.path.join(root, "queue", "logical_block_size"), default=512
            )
            if not model:
                model = name
            elif vendor:
                model = f"{vendor} {model}"
            devices.append(LinuxBlockDevice(
                number=len(devices), name=name, model=model, size_bytes=size_bytes,
                serial_number=serial, logical_sector_size=max(1, logical_sector_size),
            ))
        return devices

    def get_device(self, number):
        if number < 0:
            raise ValueError("Disk number must be non-negative")
        devices = self.list_devices()
        try:
            return devices[number]
        except IndexError as exc:
            raise OSError(f"Linux physical disk {number} is no longer available") from exc

    @staticmethod
    def _read_text(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as source:
                return source.read().strip()
        except OSError:
            return ""

    @staticmethod
    def _read_integer(path, default):
        try:
            with open(path, "r", encoding="ascii") as source:
                return int(source.read().strip())
        except (OSError, ValueError):
            return default
