from dataclasses import replace

from modules.catalog.dto import CatalogDto, CatalogNodeDto, CatalogSearchDto
from modules.recovery.extractor import Extractor


class CatalogMapper:
    @staticmethod
    def catalog(snapshot, node_ids_by_identity, disk_validation=None):
        if disk_validation is not None and getattr(snapshot, "parent_reference_issue_count", 0):
            disk_validation = dict(disk_validation)
            disk_validation["inconsistentMftRecordCount"] = (
                int(disk_validation.get("inconsistentMftRecordCount", 0))
                + int(snapshot.parent_reference_issue_count)
            )
            if disk_validation.get("assessment") == "evidence_collected":
                disk_validation["assessment"] = "inconclusive"
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
            orphaned_record_count=sum(
                bool(getattr(node, "is_orphaned", False))
                and not bool(getattr(node, "is_content_carved", False))
                for node in snapshot.catalog.nodes.values()
            ),
            content_carved_count=sum(
                bool(getattr(node, "is_content_carved", False))
                for node in snapshot.catalog.nodes.values()
            ),
            orphan_scan_performed=bool(getattr(snapshot, "orphan_scan_performed", False)),
            disk_validation=disk_validation,
            content_carving=getattr(snapshot, "content_carving_summary", None),
            low_confidence_carving=getattr(snapshot, "low_confidence_carving_summary", None),
            recycle_bin_recovery=getattr(snapshot, "recycle_bin_summary", None),
            usn_journal_evidence=getattr(snapshot, "usn_journal_summary", None),
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
            is_deleted=not bool(getattr(node.record, "is_allocated", True)),
            is_orphaned=bool(getattr(node, "is_orphaned", False)),
            is_content_carved=bool(getattr(node, "is_content_carved", False)),
            content_validation=getattr(node.record, "catalog_content_validation", None),
            cluster_allocation_status=(
                getattr(node.record, "cluster_allocation_evidence", {}).get("status")
                if isinstance(getattr(node.record, "cluster_allocation_evidence", None), dict)
                else getattr(node.record, "cluster_allocation_status", None)
            ),
            metadata_consistent=getattr(node.record, "is_metadata_consistent", None),
            recovery_source=getattr(node.record, "recovery_source", None),
            original_path=getattr(node.record, "original_path", None),
            deletion_timestamp_utc=getattr(node.record, "deletion_timestamp_utc", None),
            original_size_bytes=getattr(node.record, "recycle_bin_original_size_bytes", None),
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
