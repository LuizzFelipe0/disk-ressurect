from disk.platform import disk_reader_factory
from domain.recovery_catalog import RecoveryCatalog
from modules.catalog.models import RecoveryCatalogSnapshot
from disk.access.ports import DiskReaderFactory
from disk.deep_scan.ghost_mft_carver import GhostMFTCarver
from ntfs.tree_builder import TreeBuilder


class CatalogService:
    def __init__(self, disk_factory: DiskReaderFactory | None = None):
        self.disk_factory = disk_factory if disk_factory is not None else disk_reader_factory()

    def build(self, volume, progress_callback=None, include_orphaned=False):
        disk = self.disk_factory(volume.disk_number)
        try:
            builder = TreeBuilder(
                disk,
                volume.fragments_as_dicts(),
                volume.partition_offset,
                volume.record_size,
            )
            nodes = builder.build(progress_callback=progress_callback)
            if include_orphaned:
                from modules.recovery.extractor import Extractor

                ghosts = GhostMFTCarver(disk).hunt(
                    volume,
                    allowed_extensions=Extractor.supported_extensions(),
                    existing_records=(node.record for node in nodes.values()),
                    progress_callback=progress_callback,
                )
                builder.inject_ghosts(ghosts)
                nodes = builder.nodes
            return RecoveryCatalogSnapshot(
                catalog=RecoveryCatalog(nodes, builder.root_nodes),
                volume=volume,
                orphan_scan_performed=bool(include_orphaned),
            )
        finally:
            disk.close()

    @staticmethod
    def supported_extensions():
        from modules.recovery.extractor import Extractor

        return Extractor.supported_extensions()

    @staticmethod
    def search(snapshot, query, limit=500):
        normalized = query.casefold()
        if not normalized:
            return (), 0
        matches = [
            node for node in snapshot.catalog.nodes.values()
            if normalized in node.record.name.casefold()
            or normalized in node.full_path.casefold()
        ]
        matches.sort(key=lambda node: (node.full_path.casefold(), node.full_path))
        return tuple(matches[:limit]), len(matches)
