import os

class Carver:
    """Deep scans for files in unallocated space using magic numbers."""
    def __init__(self, disk, cluster_size=4096):
        self.disk = disk
        self.cluster_size = cluster_size
        self.chunk_size = 50 * 1024 * 1024 # 50MB
        self.max_file_size = 15 * 1024 * 1024 
        self.header = b'\xFF\xD8\xFF'
        self.footer = b'\xFF\xD9'
        self.blacklist_clusters = set()

    def set_blacklist(self, clusters):
        self.blacklist_clusters = clusters

    def carve(self, start_phys, end_phys, output_dir):
        print("[*] [Carver] Starting Deep Scan...")
        os.makedirs(output_dir, exist_ok=True)
        count = 0
        current = start_phys
        step = self.chunk_size - self.max_file_size 
        
        while current < end_phys:
            data = self.disk.read_at(current, self.chunk_size)
            if not data: break
            pos = 0
            while True:
                start_idx = data.find(self.header, pos)
                if start_idx == -1: break 
                
                phys_found = current + start_idx
                cluster_idx = phys_found // self.cluster_size
                
                # Skip if it belongs to a known/bad file (e.g. recent backup)
                if cluster_idx in self.blacklist_clusters:
                    pos = start_idx + 2
                    continue
                
                end_idx = data.find(self.footer, start_idx + 2)
                if end_idx != -1 and (end_idx - start_idx) <= self.max_file_size:
                    self._save(output_dir, count, data[start_idx : end_idx + 2])
                    count += 1
                    pos = end_idx + 2
                else:
                    pos = start_idx + 2
            current += step
        print(f"[+] [Carver] Recovered {count} orphan files.")

    def _save(self, out_dir, idx, data):
        try:
            with open(os.path.join(out_dir, f"RAW_{idx:05d}.jpg"), "wb") as f: f.write(data)
        except: pass