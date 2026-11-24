from modules.storage.entities import PhysicalDisk, StorageSource

from infrastructure.disk.factory import create_disk_reader
from infrastructure.storage.image.reader import RawImageReader


def storage_source_for_physical_disk(disk: PhysicalDisk, bytes_per_sector=512):
    return disk.as_storage_source(bytes_per_sector)


def create_block_reader(source: StorageSource):
    """Select a reader by source kind; filesystem choice stays with application."""
    if source.source_type == "physical_disk":
        reader = create_disk_reader(int(source.locator))
        actual_size = getattr(reader, "size_bytes", source.size_bytes)
        if actual_size != source.size_bytes:
            reader.close()
            raise OSError("Physical storage size changed since it was selected")
        try:
            reader.source = source
        except (AttributeError, TypeError):
            pass
        return reader
    if source.source_type == "raw_image":
        reader = RawImageReader(source.locator, source.bytes_per_sector)
        if reader.source.source_id != source.source_id:
            reader.close()
            raise OSError("Raw image identity changed since it was selected")
        return reader
    raise ValueError(f"Unsupported storage source type: {source.source_type}")
