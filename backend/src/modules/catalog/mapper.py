from modules.catalog.dto import CatalogDto, CatalogNodeDto
from modules.recovery.extractor import Extractor


class CatalogMapper:
    @staticmethod
    def catalog(snapshot, node_ids_by_identity):
        roots = tuple(
            CatalogMapper.node(node, node_ids_by_identity)
            for node in snapshot.catalog.root_nodes
        )
        return CatalogDto(
            record_count=len(snapshot.catalog.nodes),
            available_extensions=tuple(
                snapshot.catalog.available_extensions(Extractor.supported_extensions())
            ),
            roots=roots,
        )

    @staticmethod
    def node(node, node_ids_by_identity):
        return CatalogNodeDto(
            id=node_ids_by_identity[id(node)],
            name=node.record.name,
            path=node.full_path,
            is_directory=bool(node.record.is_dir),
            size_bytes=int(node.record.file_size),
            has_children=bool(node.record.is_dir and node.children),
        )
