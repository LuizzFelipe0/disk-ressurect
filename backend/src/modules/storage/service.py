from typing import Protocol

from modules.storage.entities import StorageSource


class BlockReader(Protocol):
    """Read-only positional access shared by block-backed sources."""

    @property
    def size_bytes(self) -> int: ...

    @property
    def bytes_per_sector(self) -> int: ...

    def read_at(self, offset: int, size: int) -> bytes: ...

    def close(self) -> None: ...


class BlockReaderFactory(Protocol):
    def __call__(self, source: StorageSource) -> BlockReader: ...


class PhysicalDiskEnumerator(Protocol):
    def list_disks(self): ...


class StorageService:
    """Expose storage identities and positional readers without filesystem policy."""

    def __init__(self, enumerator: PhysicalDiskEnumerator, reader_factory: BlockReaderFactory):
        self.enumerator = enumerator
        self.reader_factory = reader_factory

    def list_sources(self):
        return tuple(disk.as_storage_source() for disk in self.enumerator.list_disks())

    def get_physical_source(self, disk_number: int):
        disk = next(
            (item for item in self.enumerator.list_disks()
             if int(item.number) == int(disk_number)),
            None,
        )
        if disk is None:
            raise ValueError(f"Physical disk {disk_number} is no longer available")
        return disk.as_storage_source()

    def open_reader(self, source: StorageSource):
        return self.reader_factory(source)
