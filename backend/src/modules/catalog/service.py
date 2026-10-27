from disk.platform import disk_reader_factory
from domain.recovery_catalog import RecoveryCatalog
from modules.catalog.models import RecoveryCatalogSnapshot
from disk.access.ports import DiskReaderFactory
from ntfs.tree_builder import TreeBuilder


class CatalogService:
    def __init__(self, disk_factory: DiskReaderFactory | None = None):
        self.disk_factory = disk_factory if disk_factory is not None else disk_reader_factory()

    def build(self, volume, progress_callback=None):
        disk = self.disk_factory(volume.disk_number)
        try:
            builder = TreeBuilder(
                disk,
                volume.fragments_as_dicts(),
                volume.partition_offset,
                volume.record_size,
            )
            nodes = builder.build(progress_callback=progress_callback)
            return RecoveryCatalogSnapshot(
                catalog=RecoveryCatalog(nodes, builder.root_nodes),
                volume=volume,
            )
        finally:
            disk.close()
