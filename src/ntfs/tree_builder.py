import os
import re
from ntfs.mft_parser import MFTRecord
from utils.progress import Progress

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
    def __init__(self, disk, fragments, base_offset):
        self.disk = disk
        self.fragments = fragments
        self.base_offset = base_offset
        self.nodes = {}
        self.root_nodes = []

    def build(self):
        print("[*] [VFS] Reading MFT fragments...")
        total_records = sum(fragment["count"] for fragment in self.fragments)
        progress = Progress("MFT read", total_records, width=24)
        processed = 0
        batch_records = 4096  # 4 MiB of 1 KiB MFT records per physical read.

        for fragment in self.fragments:
            count = fragment["count"]
            base_index = fragment["base_idx"]
            read_index = 0
            while read_index < count:
                batch_count = min(batch_records, count - read_index)
                offset = fragment["phys"] + read_index * 1024
                requested_bytes = batch_count * 1024
                raw_batch = self.disk.read_at(offset, requested_bytes)
                if len(raw_batch) != requested_bytes:
                    raise OSError(
                        f"Short MFT read at {offset:#x}: "
                        f"received {len(raw_batch)} of {requested_bytes} bytes"
                    )
                complete_records = len(raw_batch) // 1024
                for item in range(complete_records):
                    begin = item * 1024
                    raw = raw_batch[begin:begin + 1024]
                    if raw[:4] == b"FILE":
                        index = base_index + read_index + item
                        record = MFTRecord(raw, index, self.disk, self.base_offset)
                        if record.is_valid and record.name:
                            self.nodes[index] = FileNode(record)
                processed += batch_count
                read_index += batch_count
                progress.update(processed)
        progress.finish()
        print("[*] [VFS] Linking parents and children...")
        self.root_nodes = []
        for index, node in self.nodes.items():
            parent_index = node.record.parent_index
            if parent_index in self.nodes and parent_index != index and index != 5:
                parent = self.nodes[parent_index]
                parent.children.append(node)
                node.parent = parent
            else:
                self.root_nodes.append(node)

        self._resolve_paths()
        return self.nodes

    def inject_ghosts(self, ghost_dict):
        """Injects orphaned records found by Deep Scan into a 'Lost Files' folder."""
        if not ghost_dict: return
        print(f"[*] [VFS] Injecting {len(ghost_dict)} ghost records into VFS...")
        for idx, rec in ghost_dict.items():
            node = FileNode(rec)
            node.full_path = os.path.join("Lost_Files_DeepScan", node.sanitize(rec.name))
            self.nodes[idx] = node

    def _resolve_paths(self):
        for root in self.root_nodes:
            self._traverse(root, "")

    def _traverse(self, node, curr_path):
        cname = node.sanitize(node.record.name)
        node.full_path = cname if node.record.index == 5 or not curr_path else os.path.join(curr_path, cname)
        # Prefix deleted files
        if not node.record.is_allocated and not node.record.is_dir:
            dir_name, file_name = os.path.split(node.full_path)
            node.full_path = os.path.join(dir_name, f"[DELETED]_{file_name}")
            
        for child in node.children:
            self._traverse(child, node.full_path)
