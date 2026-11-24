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

    def __init__(self, enumerator: PhysicalDiskEnumerator, reader_factory: BlockReaderFactory,
                 raw_image_source_factory=None):
        self.enumerator = enumerator
        self.reader_factory = reader_factory
        self.raw_image_source_factory = raw_image_source_factory
        self._registered_images = {}

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

    def register_raw_image(self, path):
        """Register a user-selected image for this process session after a read-only open."""
        if self.raw_image_source_factory is None:
            raise RuntimeError("Raw image support is unavailable")
        source = self.raw_image_source_factory(path)
        self._registered_images[source.source_id] = source
        return source

    def get_source(self, source_id):
        source = self._registered_images.get(str(source_id))
        if source is None:
            raise ValueError("Storage source is no longer registered; select it again")
        return source

    def open_reader(self, source: StorageSource):
        if source.source_type == "physical_disk":
            current = self.get_physical_source(int(source.locator))
            if current.source_id != source.source_id or current.size_bytes != source.size_bytes:
                raise OSError("Physical storage identity changed since the catalog was built")
        reader = self.reader_factory(source)
        actual_source = getattr(reader, "source", None)
        if actual_source is not None and actual_source.source_id != source.source_id:
            reader.close()
            raise OSError("Storage source identity changed since the catalog was built")
        if getattr(reader, "size_bytes", source.size_bytes) != source.size_bytes:
            reader.close()
            raise OSError("Storage source size changed since the catalog was built")
        return reader
