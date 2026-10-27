class RecoverySession:
    def __init__(self):
        self.volumes = {}
        self.snapshot = None
        self.nodes = {}

    def register_volume(self, volume):
        volume_id = f"{volume.disk_number}:{volume.partition_offset}"
        self.volumes[volume_id] = volume
        return volume_id

    def get_volume(self, volume_id):
        try:
            return self.volumes[volume_id]
        except KeyError as exc:
            raise ValueError(f"Partition candidate '{volume_id}' is not in this session") from exc

    def set_catalog(self, snapshot):
        self.snapshot = snapshot
        self.nodes = {
            f"n{index}": node
            for index, node in enumerate(snapshot.catalog.nodes.values())
        }
        return {id(node): node_id for node_id, node in self.nodes.items()}

    def get_node(self, node_id):
        try:
            return self.nodes[node_id]
        except KeyError as exc:
            raise ValueError(f"Catalog node '{node_id}' is not in this session") from exc

    def require_snapshot(self):
        if self.snapshot is None:
            raise ValueError("Build a file catalog before starting recovery")
        return self.snapshot
