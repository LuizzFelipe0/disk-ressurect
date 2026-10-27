import sys

from disk.linux_devices import LinuxBlockDeviceCatalog
from disk.models import PhysicalDisk


class LinuxDiskEnumerator:
    """List whole Linux block devices discovered through sysfs."""

    def __init__(self, catalog=None):
        self.catalog = catalog if catalog is not None else LinuxBlockDeviceCatalog()

    def list_disks(self):
        if not sys.platform.startswith("linux"):
            raise OSError("Linux physical disk inventory is only available on Linux")
        return [
            PhysicalDisk(device.number, device.model, device.size_bytes, device.serial_number)
            for device in self.catalog.list_devices()
        ]
