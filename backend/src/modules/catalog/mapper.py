from dataclasses import replace

from modules.catalog.dto import CatalogDto, CatalogNodeDto, CatalogSearchDto
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
            parent_id=node_ids_by_identity.get(id(getattr(node, "parent", None))),
        )

    @staticmethod
    def search(snapshot, nodes, total_matches, node_ids_by_identity):
        return CatalogSearchDto(
            total_matches=total_matches,
            results=tuple(CatalogMapper.search_node(node, node_ids_by_identity) for node in nodes),
        )

    @staticmethod
    def search_node(node, node_ids_by_identity):
        parent = getattr(node, "parent", None)
        ancestors = []
        while parent is not None:
            parent_id = node_ids_by_identity.get(id(parent))
            if parent_id is None:
                break
            ancestors.append(parent_id)
            parent = getattr(parent, "parent", None)
        ancestors.reverse()
        return replace(
            CatalogMapper.node(node, node_ids_by_identity),
            ancestor_ids=tuple(ancestors),
        )
