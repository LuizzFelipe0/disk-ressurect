import os
import re
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
    def __init__(self, disk, fragments, base_offset):
        self.disk = disk
        self.fragments = fragments
        self.base_offset = base_offset
        self.nodes = {}
        self.root_nodes = []

    def build(self):
        print("[*] [VFS] Reading MFT fragments...")
        for frag in self.fragments:
            for i in range(frag['count']):
                phys = frag['phys'] + (i * 1024)
                raw = self.disk.read_at(phys, 1024)
                if raw[:4] == b"FILE":
                    idx = frag['base_idx'] + i
                    rec = MFTRecord(raw, idx, self.disk, self.base_offset)
                    if rec.is_valid and rec.name:
                        self.nodes[idx] = FileNode(rec)
        
        print("[*] [VFS] Linking parents and children...")
        for idx, node in self.nodes.items():
            pid = node.record.parent_index
            if pid in self.nodes and pid != idx and idx != 5:
                pnode = self.nodes[pid]
                pnode.children.append(node)
                node.parent = pnode
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