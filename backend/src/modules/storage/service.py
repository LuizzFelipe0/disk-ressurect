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
