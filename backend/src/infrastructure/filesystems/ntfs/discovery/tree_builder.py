import os
import re
from typing import Callable

from infrastructure.filesystems.ntfs.mft.parser import MFTRecord
from infrastructure.filesystems.ntfs.mft.data_extent_resolver import MFTDataExtentResolver


class FileNode:
    def __init__(self, record, *, is_orphaned=False, is_content_carved=False):
        self.record = record
        self.children = []
        self.parent = None
        self.full_path = ""
        self.is_orphaned = bool(is_orphaned)
        self.is_content_carved = bool(is_content_carved)
        
    def sanitize(self, name):
        return re.sub(r'[\\/*?:"<>|]', "_", name).strip()

class TreeBuilder:
    """Builds a Virtual File System (VFS) in memory."""
    def __init__(
        self, disk, fragments, base_offset, record_size=1024, *,
        cluster_size=None, volume_size_bytes=None,
    ):
        self.disk = disk
        self.fragments = fragments
        self.base_offset = base_offset
        self.record_size = int(record_size)
        self.cluster_size = None if cluster_size is None else int(cluster_size)
        self.volume_size_bytes = (
            None if volume_size_bytes is None else int(volume_size_bytes)
        )
        if self.record_size < 512 or self.record_size % 512:
            raise ValueError("MFT record size must be a positive multiple of 512 bytes")
        self.nodes = {}
        self.mft_records = {}
        self.data_extent_resolution_counts = {
            "resolved": 0,
            "inconclusive": 0,
        }
        self.root_nodes = []
        self.parent_reference_issue_count = 0

    def build(
        self,
        progress_callback: Callable[[int, int], None] | None = None,
        phase_callback: Callable[[str, int, int], None] | None = None,
    ):
        total_records = sum(fragment["count"] for fragment in self.fragments)
        processed = 0
        batch_records = max(1, (4 * 1024 * 1024) // self.record_size)

        for fragment in self.fragments:
            count = fragment["count"]
            base_index = fragment["base_idx"]
            read_index = 0
            while read_index < count:
                batch_count = min(batch_records, count - read_index)
                offset = fragment["phys"] + read_index * self.record_size
                requested_bytes = batch_count * self.record_size
                raw_batch = self.disk.read_at(offset, requested_bytes)
                if len(raw_batch) != requested_bytes:
                    raise OSError(
                        f"Short MFT read at {offset:#x}: "
                        f"received {len(raw_batch)} of {requested_bytes} bytes"
                    )
                complete_records = len(raw_batch) // self.record_size
                for item in range(complete_records):
                    begin = item * self.record_size
                    raw = raw_batch[begin:begin + self.record_size]
                    if raw[:4] == b"FILE":
                        index = base_index + read_index + item
                        record = MFTRecord(
                            raw,
                            index,
                            self.disk,
                            offset + begin,
                            self.record_size,
                        )
                        if record.is_valid:
                            self.mft_records[index] = record
                            if record.name and not record.is_extension_record:
                                self.nodes[index] = FileNode(record)
                processed += batch_count
                read_index += batch_count
                if progress_callback is not None:
                    progress_callback(processed, total_records)
        self._resolve_fragmented_data_runs()
        node_total = len(self.nodes)
        self._report_phase(phase_callback, "linking", 0, node_total)
        self._link_nodes(phase_callback)
        self.parent_reference_issue_count = sum(
            any(warning in getattr(node.record, "metadata_warnings", ()) for warning in (
                "parent_sequence_number_does_not_match_parent_record",
                "parent_reference_targets_non_directory",
            ))
            for node in self.nodes.values()
        )
        self._detach_parent_cycles(phase_callback)
        self.root_nodes = [node for node in self.nodes.values() if node.parent is None]

        self._resolve_paths(phase_callback)
        return self.nodes

    def _resolve_fragmented_data_runs(self):
        if (self.cluster_size is None or self.cluster_size <= 0
                or self.volume_size_bytes is None or self.volume_size_bytes <= 0):
            return
        resolver = MFTDataExtentResolver()
        for record in self.mft_records.values():
            if (record.is_extension_record or not record.has_attribute_list
                    or not record.name or record.is_dir):
                continue
            result = resolver.resolve(
                record,
                self.mft_records,
                cluster_size=self.cluster_size,
                volume_size_bytes=self.volume_size_bytes,
            )
            record.data_extent_resolution = result.status
            record.data_extent_resolution_reason = result.reason
            record.data_extent_count = result.extent_count
            if result.status == "resolved":
                record.data_runs = list(result.data_runs)
                record.data_is_complete = True
                self.data_extent_resolution_counts["resolved"] += 1
            elif result.status == "inconclusive":
                self.data_extent_resolution_counts["inconclusive"] += 1

    def _link_nodes(self, phase_callback=None):
        node_total = len(self.nodes)
        for position, (index, node) in enumerate(self.nodes.items(), start=1):
            parent_index = getattr(node.record, "parent_index", None)
            parent = self.nodes.get(parent_index)
            if parent is not None and parent_index != index and index != 5:
                expected_sequence = getattr(node.record, "parent_sequence_number", None)
                actual_sequence = getattr(parent.record, "sequence_number", None)
                if not parent.record.is_dir:
                    self._mark_metadata_inconsistent(
                        node.record, "parent_reference_targets_non_directory",
                    )
                elif expected_sequence is None or expected_sequence == actual_sequence:
                    parent.children.append(node)
                    node.parent = parent
                else:
                    self._mark_metadata_inconsistent(
                        node.record, "parent_sequence_number_does_not_match_parent_record",
                    )
            if position % 4096 == 0 or position == node_total:
                self._report_phase(phase_callback, "linking", position, node_total)

    @staticmethod
    def _mark_metadata_inconsistent(record, warning):
        warnings = getattr(record, "metadata_warnings", None)
        if warnings is not None and warning not in warnings:
            warnings.append(warning)
        if hasattr(record, "is_metadata_consistent"):
            record.is_metadata_consistent = False

    def inject_ghosts(self, ghost_dict):
        """Add carved entries as isolated roots with unique, safe output paths."""
        for synthetic_id, record in ghost_dict.items():
            if synthetic_id in self.nodes:
                raise ValueError(f"Carved MFT record ID collides with catalog ID {synthetic_id}")
            node = FileNode(record, is_orphaned=True)
            source_offset = int(record.mft_offset)
            safe_name = node.sanitize(record.name) or "unnamed"
            node.full_path = os.path.join(
                "Lost_Files_DeepScan",
                f"{source_offset:016X}",
                f"[DELETED]_{safe_name}",
            )
            self.nodes[synthetic_id] = node
            self.root_nodes.append(node)

    def _resolve_paths(self, phase_callback=None):
        visited = set()
        pending = [(root, "") for root in reversed(self.root_nodes)]
        total = len(self.nodes)
        self._report_phase(phase_callback, "paths", 0, total)
        while pending:
            node, parent_path = pending.pop()
            identity = id(node)
            if identity in visited:
                continue
            visited.add(identity)
            name = node.sanitize(node.record.name)
            node.full_path = (
                name if node.record.index == 5 or not parent_path
                else os.path.join(parent_path, name)
            )
            if not node.record.is_allocated and not node.record.is_dir:
                directory, filename = os.path.split(node.full_path)
                node.full_path = os.path.join(directory, f"[DELETED]_{filename}")
            pending.extend((child, node.full_path) for child in reversed(node.children))
            if len(visited) % 4096 == 0 or len(visited) == total:
                self._report_phase(phase_callback, "paths", len(visited), total)

        # Preserve disconnected records in the catalog even if a damaged parent
        # reference made them unreachable from every valid root.
        for node in self.nodes.values():
            if id(node) not in visited:
                node.full_path = node.sanitize(node.record.name)
                visited.add(id(node))
                if len(visited) % 4096 == 0 or len(visited) == total:
                    self._report_phase(phase_callback, "paths", len(visited), total)

    def _detach_parent_cycles(self, phase_callback=None):
        """Break corrupt parent-reference cycles at a deterministic record."""
        visited = set()
        total = len(self.nodes)
        self._report_phase(phase_callback, "hierarchy", 0, total)
        processed = 0
        for position, start in enumerate(self.nodes.values(), start=1):
            chain = []
            positions = {}
            current = start
            while current is not None and id(current) not in visited:
                identity = id(current)
                if identity in positions:
                    cycle = chain[positions[identity]:]
                    detached = min(cycle, key=lambda item: item.record.index)
                    if detached.parent is not None:
                        detached.parent.children.remove(detached)
                        detached.parent = None
                    break
                positions[identity] = len(chain)
                chain.append(current)
                processed += 1
                current = current.parent
                if processed % 4096 == 0:
                    self._report_phase(phase_callback, "hierarchy", processed, total)
            visited.update(id(node) for node in chain)
            if position % 4096 == 0 or position == total:
                self._report_phase(phase_callback, "hierarchy", max(processed, position), total)

    @staticmethod
    def _report_phase(callback, phase, completed, total):
        if callback is not None:
            callback(phase, completed, total)
