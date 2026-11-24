class RecoverySession:
    def __init__(self):
        self.volumes = {}
        self.volume_source_ids = {}
        self.snapshot = None
        self.nodes = {}

    def register_volume(self, volume, source_id=None):
        source_id = source_id or getattr(volume, "source_id", None)
        volume_id = (f"{source_id}:{volume.partition_offset}" if source_id
                     else f"{volume.disk_number}:{volume.partition_offset}")
        self.volumes[volume_id] = volume
        if source_id:
            self.volume_source_ids[volume_id] = source_id
        return volume_id

    def get_volume(self, volume_id):
        try:
            return self.volumes[volume_id]
        except KeyError as exc:
            raise ValueError(f"Partition candidate '{volume_id}' is not in this session") from exc

    def get_volume_source_id(self, volume_id):
        return self.volume_source_ids.get(volume_id)

    def set_catalog(self, snapshot):
        self.snapshot = snapshot
        self.nodes = {
            getattr(node, "node_id", f"n{index}"): node
            for index, node in enumerate(snapshot.catalog.nodes.values())
        }
        return self.node_ids_by_identity()

    def node_ids_by_identity(self):
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
