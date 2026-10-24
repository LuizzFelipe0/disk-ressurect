import os

from utils.progress import Progress

class Extractor:
    """Extracts valid files using header validation."""
    def __init__(self, disk, vfs_nodes, vol_start, cluster_size=4096):
        self.disk = disk
        self.nodes = vfs_nodes
        self.vol_start = vol_start
        self.c_size = cluster_size
        self.filters = {'ext': set(), 'dirs': set(), 'min_kb': 0}
        self.sigs = {'.jpg': b'\xFF\xD8', '.jpeg': b'\xFF\xD8', '.pdf': b'%PDF', '.png': b'\x89PNG'}

    def set_filters(self, exts, dirs, min_kb):
        self.filters['ext'] = {e.lower() for e in exts}
        self.filters['dirs'] = {d.lower() for d in dirs}
        self.filters['min_kb'] = min_kb

    def _should_extract(self, node):
        if node.record.is_dir or node.record.file_size <= (self.filters['min_kb'] * 1024): return False
        ext = os.path.splitext(node.record.name.lower())[1]
        if self.filters['ext'] and ext not in self.filters['ext']: return False
        path_lower = node.full_path.lower()
        if self.filters['dirs'] and any(d in path_lower for d in self.filters['dirs']): return False
        return True

    def extract(self, out_dir):
        targets = [n for n in self.nodes.values() if self._should_extract(n)]
        print(f"[*] [Extractor] Starting extraction of {len(targets)} files...")
        progress = Progress("File extraction", len(targets), width=24)
        extracted = 0
        for target_index, node in enumerate(targets, 1):
            dest = os.path.join(out_dir, node.full_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            
            try:
                with open(dest, "wb") as f:
                    if node.record.resident_data:
                        f.write(node.record.resident_data)
                        extracted += 1
                    else:
                        left = node.record.file_size
                        first_chunk = True
                        for lcn, length in node.record.data_runs:
                            if left <= 0: break
                            read_sz = length * self.c_size
                            if lcn is None:
                                f.write(b'\x00' * min(read_sz, left))
                                left -= read_sz
                            else:
                                chunk = self.disk.read_at(self.vol_start + (lcn * self.c_size), read_sz)
                                if first_chunk:
                                    ext = os.path.splitext(node.record.name.lower())[1]
                                    expected = self.sigs.get(ext)
                                    if expected and not chunk.startswith(expected):
                                        f.close()
                                        os.remove(dest)
                                        break # Skip corrupted file
                                    first_chunk = False
                                
                                to_write = min(len(chunk), left)
                                f.write(chunk[:to_write])
                                left -= to_write
                        if not first_chunk: extracted += 1
            except: pass
        return extracted