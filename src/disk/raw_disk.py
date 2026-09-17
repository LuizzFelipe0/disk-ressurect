import ctypes
import os

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
        self.handle = self._open_disk()
        self.size = self._get_size()

    def _open_disk(self):
        h = ctypes.windll.kernel32.CreateFileW(self.path, 0x80000000, 0x01 | 0x02, None, 3, 0, None)
        if h == -1: raise PermissionError("Must run as Administrator!")
        return h

    def _get_size(self):
        IOCTL_DISK_GET_DRIVE_GEOMETRY_EX = 0x000700A0
        out = ctypes.create_string_buffer(1024)
        returned = ctypes.c_uint32(0)
        ok = ctypes.windll.kernel32.DeviceIoControl(self.handle, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, None, 0, out, len(out), ctypes.byref(returned), None)
        if not ok: return 0
        geom = DISK_GEOMETRY_EX.from_buffer_copy(out.raw[:ctypes.sizeof(DISK_GEOMETRY_EX)])
        return geom.DiskSize.QuadPart

    def read_at(self, offset, size):
        got = ctypes.c_uint32(0)
        buf = ctypes.create_string_buffer(size)
        ctypes.windll.kernel32.SetFilePointerEx(self.handle, ctypes.c_longlong(offset), None, 0)
        ctypes.windll.kernel32.ReadFile(self.handle, buf, size, ctypes.byref(got), None)
        return buf.raw

    def close(self):
        ctypes.windll.kernel32.CloseHandle(self.handle)