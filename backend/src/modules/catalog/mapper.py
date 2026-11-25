from dataclasses import replace

from modules.catalog.dto import CatalogDto, CatalogNodeDto, CatalogSearchDto
from modules.catalog.entities import SUPPORTED_CATALOG_EXTENSIONS


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
                snapshot.catalog.available_extensions(SUPPORTED_CATALOG_EXTENSIONS)
            ),
            roots=roots,
            orphaned_record_count=sum(
                bool(CatalogMapper._properties(node).get("isOrphaned", False))
                and not bool(CatalogMapper._properties(node).get("isContentCarved", False))
                for node in snapshot.catalog.nodes.values()
            ),
            content_carved_count=sum(
                bool(CatalogMapper._properties(node).get("isContentCarved", False))
                for node in snapshot.catalog.nodes.values()
            ),
            orphan_scan_performed=bool(getattr(snapshot, "orphan_scan_performed", False)),
            disk_validation=disk_validation,
            content_carving=getattr(snapshot, "content_carving_summary", None),
            low_confidence_carving=getattr(snapshot, "low_confidence_carving_summary", None),
            recycle_bin_recovery=getattr(snapshot, "recycle_bin_summary", None),
            usn_journal_evidence=getattr(snapshot, "usn_journal_summary", None),
            ntfs_log_file_evidence=getattr(snapshot, "ntfs_log_file_summary", None),
        )

    @staticmethod
    def node(node, node_ids_by_identity):
        properties = CatalogMapper._properties(node)
        record = getattr(node, "record", None)
        name = getattr(node, "name", getattr(record, "name", ""))
        full_path = getattr(node, "full_path", name)
        is_directory = getattr(node, "is_directory", bool(getattr(record, "is_dir", False)))
        size_bytes = getattr(node, "size_bytes", getattr(record, "file_size", 0))
        extent_resolution = properties.get("dataExtentResolution")
        return CatalogNodeDto(
            id=CatalogMapper._node_id(node, node_ids_by_identity),
            name=name,
            path=full_path,
            is_directory=is_directory,
            size_bytes=int(size_bytes),
            has_children=bool(is_directory and node.children),
            parent_id=CatalogMapper._node_id(getattr(node, "parent", None), node_ids_by_identity),
            is_deleted=bool(properties.get("isDeleted", False)),
            is_orphaned=bool(properties.get("isOrphaned", False)),
            is_content_carved=bool(properties.get("isContentCarved", False)),
            content_validation=properties.get("contentValidation"),
            cluster_allocation_status=properties.get("clusterAllocationStatus"),
            metadata_consistent=properties.get("metadataConsistent"),
            recovery_source=properties.get("recoverySource"),
            original_path=properties.get("originalPath"),
            deletion_timestamp_utc=properties.get("deletionTimestampUtc"),
            original_size_bytes=properties.get("originalSizeBytes"),
            data_extent_resolution=(
                extent_resolution
                if extent_resolution in {"resolved", "inconclusive"} else None
            ),
            data_extent_resolution_reason=properties.get("dataExtentResolutionReason"),
            data_extent_count=(
                int(properties.get("dataExtentCount", 0))
                if extent_resolution == "resolved"
                else None
            ),
        )

    @staticmethod
    def _properties(node):
        properties = getattr(node, "properties", None)
        if properties is not None:
            return properties
        # Keep DTO mapping compatible while callers migrate from legacy adapters.
        record = getattr(node, "record", None)
        if record is None:
            return {}
        allocation = getattr(record, "cluster_allocation_evidence", None)
        return {
            "isDeleted": not bool(getattr(record, "is_allocated", True)),
            "isOrphaned": bool(getattr(node, "is_orphaned", False)),
            "isContentCarved": bool(getattr(node, "is_content_carved", False)),
            "contentValidation": getattr(record, "catalog_content_validation", None),
            "clusterAllocationStatus": (
                allocation.get("status") if isinstance(allocation, dict)
                else getattr(record, "cluster_allocation_status", None)
            ),
            "metadataConsistent": getattr(record, "is_metadata_consistent", None),
        }

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
            parent_id = CatalogMapper._node_id(parent, node_ids_by_identity)
            if parent_id is None:
                break
            ancestors.append(parent_id)
            parent = getattr(parent, "parent", None)
        ancestors.reverse()
        return replace(
            CatalogMapper.node(node, node_ids_by_identity),
            ancestor_ids=tuple(ancestors),
        )

    @staticmethod
    def _node_id(node, node_ids_by_identity):
        if node is None:
            return None
        mapped_id = node_ids_by_identity.get(id(node))
        if mapped_id is not None:
            return mapped_id
        node_id = getattr(node, "node_id", None)
        if node_id is not None:
            return node_id
        return None
