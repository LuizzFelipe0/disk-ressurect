import os
import re
from typing import Callable
from ntfs.mft_parser import MFTRecord

class FileNode:
    def __init__(self, record):
        self.record = record
        self.children = []
        self.parent = None
        self.full_path = ""
        
    def sanitize(self, name):
        return re.sub(r'[\\/*?:"<>|]', "_", name).strip()

class TreeBuilder:
    """Builds a Virtual File System (VFS) in memory."""
    def __init__(self, disk, fragments, base_offset, record_size=1024):
        self.disk = disk
        self.fragments = fragments
        self.base_offset = base_offset
        self.record_size = int(record_size)
        if self.record_size < 512 or self.record_size % 512:
            raise ValueError("MFT record size must be a positive multiple of 512 bytes")
        self.nodes = {}
        self.root_nodes = []

    def build(self, progress_callback: Callable[[int, int], None] | None = None):
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
                        if record.is_valid and record.name:
                            self.nodes[index] = FileNode(record)
                processed += batch_count
                read_index += batch_count
                if progress_callback is not None:
                    progress_callback(processed, total_records)
        for index, node in self.nodes.items():
            parent_index = node.record.parent_index
            parent = self.nodes.get(parent_index)
            if (parent is not None and parent.record.is_dir
                    and parent_index != index and index != 5):
                parent.children.append(node)
                node.parent = parent

        self._detach_parent_cycles()
        self.root_nodes = [node for node in self.nodes.values() if node.parent is None]

        self._resolve_paths()
        return self.nodes

    def inject_ghosts(self, ghost_dict):
        if not ghost_dict: return
        for idx, rec in ghost_dict.items():
            node = FileNode(rec)
            node.full_path = os.path.join("Lost_Files_DeepScan", node.sanitize(rec.name))
            self.nodes[idx] = node

    def _resolve_paths(self):
        visited = set()
        pending = [(root, "") for root in reversed(self.root_nodes)]
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

        # Preserve disconnected records in the catalog even if a damaged parent
        # reference made them unreachable from every valid root.
        for node in self.nodes.values():
            if id(node) not in visited:
                node.full_path = node.sanitize(node.record.name)

    def _detach_parent_cycles(self):
        """Break corrupt parent-reference cycles at a deterministic record."""
        visited = set()
        for start in self.nodes.values():
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
                current = current.parent
            visited.update(id(node) for node in chain)
