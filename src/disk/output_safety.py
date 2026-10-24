"""Prevent recovery output from being written onto the source physical disk."""

import ctypes
import os
import struct
from ctypes import wintypes


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
    """Return physical disk numbers backing the volume containing ``path``."""
    if os.name != "nt":
        raise OSError("Output volume mapping is only implemented on Windows")
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
