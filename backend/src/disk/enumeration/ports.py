from typing import Protocol

from disk.models import PhysicalDisk


class DiskEnumerator(Protocol):
    def list_disks(self) -> list[PhysicalDisk]: ...
