import os
import sys


def create_disk_enumerator():
    if os.name == "nt":
        from disk.enumeration.windows import WindowsDiskEnumerator
        return WindowsDiskEnumerator()
    if sys.platform.startswith("linux"):
        from disk.enumeration.linux import LinuxDiskEnumerator
        return LinuxDiskEnumerator()
    raise OSError(f"Physical disk discovery is not supported on {sys.platform}")


def create_disk_reader(disk_number):
    if os.name == "nt":
        from disk.access.raw_disk import RawDisk
        return RawDisk(disk_number)
    if sys.platform.startswith("linux"):
        from disk.access.linux_disk import LinuxDiskReader
        return LinuxDiskReader(disk_number)
    raise OSError(f"Physical disk reads are not supported on {sys.platform}")


def disk_reader_factory():
    return create_disk_reader
