import os
import sys


def create_disk_enumerator():
    if os.name == "nt":
        from infrastructure.disk.windows.enumeration import WindowsDiskEnumerator
        return WindowsDiskEnumerator()
    if sys.platform.startswith("linux"):
        from infrastructure.disk.linux.enumeration import LinuxDiskEnumerator
        return LinuxDiskEnumerator()
    raise OSError(f"Physical disk discovery is not supported on {sys.platform}")


def create_disk_reader(disk_number):
    if os.name == "nt":
        from infrastructure.disk.windows.reader import RawDisk
        return RawDisk(disk_number)
    if sys.platform.startswith("linux"):
        from infrastructure.disk.linux.reader import LinuxDiskReader
        return LinuxDiskReader(disk_number)
    raise OSError(f"Physical disk reads are not supported on {sys.platform}")


def disk_reader_factory():
    return create_disk_reader
