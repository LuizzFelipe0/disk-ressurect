import ctypes
import os
import threading
from ctypes import wintypes

class LARGE_INTEGER(ctypes.Structure):
    _fields_ = [("QuadPart", ctypes.c_longlong)]

class DISK_GEOMETRY(ctypes.Structure):
    _fields_ = [
        ("Cylinders", LARGE_INTEGER), ("MediaType", ctypes.c_uint32),
        ("TracksPerCylinder", ctypes.c_uint32), ("SectorsPerTrack", ctypes.c_uint32),
        ("BytesPerSector", ctypes.c_uint32),
    ]

class DISK_GEOMETRY_EX(ctypes.Structure):
    _fields_ = [("Geometry", DISK_GEOMETRY), ("DiskSize", LARGE_INTEGER)]

class RawDisk:
    """Handles low-level physical disk operations."""
    def __init__(self, disk_number):
        self.path = rf"\\.\PhysicalDrive{disk_number}"
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_api()
        self._read_lock = threading.Lock()
        self._closed = False
        self.handle = self._open_disk()
        try:
            self.bytes_per_sector = 512
            self.size = self._get_size()
        except Exception:
            self._kernel32.CloseHandle(self.handle)
            self._closed = True
            raise

    def _configure_api(self):
        kernel32 = self._kernel32
        kernel32.CreateFileW.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        )
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.SetFilePointerEx.argtypes = (
            wintypes.HANDLE, LARGE_INTEGER, ctypes.POINTER(LARGE_INTEGER), wintypes.DWORD,
        )
        kernel32.SetFilePointerEx.restype = wintypes.BOOL
        kernel32.ReadFile.argtypes = (
            wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
        )
        kernel32.ReadFile.restype = wintypes.BOOL
        kernel32.DeviceIoControl.argtypes = (
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
            wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
        )
        kernel32.DeviceIoControl.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

    @staticmethod
    def _validated_read_length(success, bytes_read, requested):
        """Validate the Win32 read result while preserving legitimate short reads."""
        if not success:
            raise OSError("ReadFile failed while reading the physical disk")
        if bytes_read < 0 or bytes_read > requested:
            raise OSError(f"ReadFile returned an invalid byte count: {bytes_read}/{requested}")
        return bytes_read

    def _open_disk(self):
        h = self._kernel32.CreateFileW(
            self.path, 0x80000000, 0x01 | 0x02, None, 3, 0, None
        )
        if h == wintypes.HANDLE(-1).value:
            error = ctypes.get_last_error()
            if error == 5:
                raise PermissionError("Must run as Administrator to read a physical disk")
            raise ctypes.WinError(error, f"Could not open {self.path}")
        return h

    def _get_size(self):
        IOCTL_DISK_GET_DRIVE_GEOMETRY_EX = 0x000700A0
        out = ctypes.create_string_buffer(1024)
        returned = ctypes.c_uint32(0)
        ok = self._kernel32.DeviceIoControl(
            self.handle, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, None, 0,
            out, len(out), ctypes.byref(returned), None,
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error(), "Could not read physical disk geometry")
        if returned.value < ctypes.sizeof(DISK_GEOMETRY_EX):
            raise OSError("Physical disk geometry response was incomplete")
        geom = DISK_GEOMETRY_EX.from_buffer_copy(out.raw[:ctypes.sizeof(DISK_GEOMETRY_EX)])
        if geom.Geometry.BytesPerSector <= 0:
            raise OSError("Physical disk reported an invalid sector size")
        self.bytes_per_sector = geom.Geometry.BytesPerSector
        return geom.DiskSize.QuadPart

    @staticmethod
    def _aligned_read_parameters(offset, size, sector_size, disk_size):
        if sector_size <= 0:
            raise ValueError("Sector size must be positive")
        if offset >= disk_size:
            return offset, 0, 0, 0
        logical_size = min(size, disk_size - offset)
        aligned_offset = offset - offset % sector_size
        requested_end = offset + logical_size
        aligned_end = ((requested_end + sector_size - 1) // sector_size) * sector_size
        aligned_end = min(aligned_end, disk_size)
        return aligned_offset, aligned_end - aligned_offset, offset - aligned_offset, logical_size

    def read_at(self, offset, size):
        if offset < 0 or size < 0:
            raise ValueError("Disk offsets and read sizes must be non-negative")
        if size > 0xFFFFFFFF:
            raise ValueError("A single ReadFile request cannot exceed 4 GiB")
        if size == 0:
            return b""

        aligned_offset, aligned_size, slice_offset, logical_size = self._aligned_read_parameters(
            offset, size, self.bytes_per_sector, self.size
        )
        if aligned_size == 0:
            return b""
        if aligned_size > 0xFFFFFFFF:
            raise ValueError("Aligned ReadFile request cannot exceed 4 GiB")

        got = wintypes.DWORD(0)
        buf = ctypes.create_string_buffer(aligned_size)
        with self._read_lock:
            if self._closed:
                raise OSError("Physical disk handle is closed")
            if not self._kernel32.SetFilePointerEx(
                self.handle, LARGE_INTEGER(aligned_offset), None, 0
            ):
                raise ctypes.WinError(ctypes.get_last_error(), f"Could not seek to offset {aligned_offset}")
            success = self._kernel32.ReadFile(
                self.handle, buf, aligned_size, ctypes.byref(got), None
            )
        if not success:
            raise ctypes.WinError(
                ctypes.get_last_error(),
                f"Could not read {aligned_size} sector-aligned bytes at offset {aligned_offset}",
            )
        byte_count = self._validated_read_length(True, got.value, aligned_size)
        available = max(0, byte_count - slice_offset)
        return buf[slice_offset:slice_offset + min(logical_size, available)]

    def close(self):
        with self._read_lock:
            if not self._closed:
                if not self._kernel32.CloseHandle(self.handle):
                    raise ctypes.WinError(ctypes.get_last_error(), "Could not close physical disk")
                self._closed = True
