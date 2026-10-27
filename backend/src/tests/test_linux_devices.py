import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from disk.enumeration.linux import LinuxDiskEnumerator
from disk.linux_devices import LinuxBlockDeviceCatalog


class LinuxBlockDeviceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory(dir=os.path.dirname(__file__))
        self.addCleanup(self.temporary_directory.cleanup)
        self.sys_block_path = os.path.join(self.temporary_directory.name, "sys", "block")
        self.device_path = os.path.join(self.temporary_directory.name, "dev")
        os.makedirs(self.device_path)
        self._add_device("sda", 100, "Example Disk", "SERIAL-A")
        self._add_device("nvme0n1", 200, "Example NVMe", "SERIAL-B")
        self._add_device("loop0", 500, "Loop Device", "")
        self.catalog = LinuxBlockDeviceCatalog(self.sys_block_path, self.device_path)

    def _add_device(self, name, size_sectors, model, serial):
        root = os.path.join(self.sys_block_path, name)
        os.makedirs(os.path.join(root, "queue"), exist_ok=True)
        os.makedirs(os.path.join(root, "device"), exist_ok=True)
        with open(os.path.join(root, "size"), "w", encoding="ascii") as target:
            target.write(str(size_sectors))
        with open(os.path.join(root, "queue", "logical_block_size"), "w", encoding="ascii") as target:
            target.write("4096")
        with open(os.path.join(root, "device", "model"), "w", encoding="utf-8") as target:
            target.write(model)
        with open(os.path.join(root, "device", "serial"), "w", encoding="utf-8") as target:
            target.write(serial)

    def test_lists_whole_devices_and_skips_pseudo_devices(self):
        devices = self.catalog.list_devices()

        self.assertEqual([device.name for device in devices], ["nvme0n1", "sda"])
        self.assertEqual([device.number for device in devices], [0, 1])
        self.assertEqual(devices[0].size_bytes, 200 * 512)
        self.assertEqual(devices[0].logical_sector_size, 4096)
        self.assertEqual(devices[1].serial_number, "SERIAL-A")

    def test_get_device_rejects_a_missing_disk_number(self):
        with self.assertRaisesRegex(OSError, "no longer available"):
            self.catalog.get_device(5)

    def test_enumerator_maps_sysfs_devices_to_application_disks(self):
        with patch("disk.enumeration.linux.sys.platform", "linux"):
            disks = LinuxDiskEnumerator(self.catalog).list_disks()

        self.assertEqual([disk.number for disk in disks], [0, 1])
        self.assertEqual([disk.model for disk in disks], ["Example NVMe", "Example Disk"])


if __name__ == "__main__":
    unittest.main()
