import ctypes
import os
import struct
import sys
from ctypes import wintypes
from disk.linux_devices import LinuxBlockDeviceCatalog


IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x00560000


def _existing_ancestor(path):
    current = os.path.abspath(path)
    while not os.path.exists(current):
        parent = os.path.dirname(current)
        if parent == current:
            raise OSError(f"Could not resolve an existing parent for output path: {path}")
        current = parent
    return current


def volume_disk_numbers(path):
    if os.name == "nt":
        return _windows_volume_disk_numbers(path)
    if sys.platform.startswith("linux"):
        return _linux_volume_disk_numbers(path)
    raise OSError(f"Output volume mapping is not implemented on {sys.platform}")


def _windows_volume_disk_numbers(path):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetVolumePathNameW.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    kernel32.GetVolumePathNameW.restype = wintypes.BOOL
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.DeviceIoControl.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    )
    kernel32.DeviceIoControl.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    ancestor = _existing_ancestor(path)
    volume_root = ctypes.create_unicode_buffer(1024)
    if not kernel32.GetVolumePathNameW(ancestor, volume_root, len(volume_root)):
        raise ctypes.WinError(ctypes.get_last_error(), f"Could not resolve output volume for {path}")
    drive, _ = os.path.splitdrive(volume_root.value.rstrip("\\/"))
    if not drive:
        raise OSError(f"Could not resolve a drive letter for output volume: {volume_root.value}")

    handle = kernel32.CreateFileW(
        rf"\\.\{drive}", 0, 0x01 | 0x02 | 0x04, None, 3, 0, None
    )
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error(), f"Could not open output volume {drive}")
    try:
        buffer = ctypes.create_string_buffer(4096)
        returned = wintypes.DWORD(0)
        if not kernel32.DeviceIoControl(
            handle, IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS, None, 0,
            buffer, len(buffer), ctypes.byref(returned), None,
        ):
            raise ctypes.WinError(ctypes.get_last_error(), f"Could not map output volume {drive} to a physical disk")
        if returned.value < 8:
            raise OSError("Volume disk extent response was incomplete")
        count = struct.unpack_from("<I", buffer.raw, 0)[0]
        extent_size = 24  # DWORD disk number, alignment padding, two LARGE_INTEGER fields.
        if count == 0 or 8 + count * extent_size > returned.value:
            raise OSError("Volume disk extent response has invalid bounds")
        return {
            struct.unpack_from("<I", buffer.raw, 8 + index * extent_size)[0]
            for index in range(count)
        }
    finally:
        kernel32.CloseHandle(handle)


def _linux_volume_disk_numbers(path, catalog=None, sys_dev_block_path="/sys/dev/block"):
    ancestor = _existing_ancestor(path)
    device_id = os.stat(ancestor).st_dev
    major, minor = os.major(device_id), os.minor(device_id)
    sysfs_device = os.path.realpath(os.path.join(sys_dev_block_path, f"{major}:{minor}"))
    if not os.path.exists(sysfs_device):
        raise OSError(f"Could not map output filesystem device {major}:{minor} to a block device")

    device_catalog = catalog if catalog is not None else LinuxBlockDeviceCatalog()
    number_by_name = {device.name: device.number for device in device_catalog.list_devices()}
    backing_names = set()
    visited = set()

    def visit(device_path):
        device_path = os.path.realpath(device_path)
        if device_path in visited:
            return
        visited.add(device_path)
        slaves_path = os.path.join(device_path, "slaves")
        try:
            slaves = os.listdir(slaves_path)
        except OSError:
            slaves = []
        if slaves:
            for slave in slaves:
                visit(os.path.join(slaves_path, slave))
            return
        if os.path.exists(os.path.join(device_path, "partition")):
            device_path = os.path.dirname(device_path)
        backing_names.add(os.path.basename(device_path))

    visit(sysfs_device)
    disk_numbers = {number_by_name[name] for name in backing_names if name in number_by_name}
    if not disk_numbers:
        raise OSError(f"Could not identify physical disks backing output path: {path}")
    return disk_numbers


class OutputSafetyGuard:
    """Fail closed when output volume shares a physical disk with the source."""

    def __init__(self, disk_mapper=volume_disk_numbers):
        self.disk_mapper = disk_mapper

    def validate(self, output_path, source_disk_number):
        disks = self.disk_mapper(output_path)
        if not disks:
            raise OSError(f"Could not identify physical disks for output path: {output_path}")
        if source_disk_number in disks:
            raise ValueError(
                f"Recovery output {output_path!r} is on source disk {source_disk_number}; "
                "choose a different physical disk to avoid overwriting recoverable data"
            )
        return sorted(disks)
