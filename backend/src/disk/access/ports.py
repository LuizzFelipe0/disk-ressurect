from typing import Protocol


class DiskReader(Protocol):
    size: int
    bytes_per_sector: int

    def read_at(self, offset: int, size: int) -> bytes: ...

    def close(self) -> None: ...


class DiskReaderFactory(Protocol):
    def __call__(self, disk_number: int) -> DiskReader: ...
