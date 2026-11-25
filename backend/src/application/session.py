class RecoverySession:
    def __init__(self):
        self.volumes = {}
        self.volume_source_ids = {}
        self.snapshot = None
        self.nodes = {}
        self._node_ids_by_identity = {}

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
        self.nodes = snapshot.catalog.nodes
        self._node_ids_by_identity = {}
        return self.node_ids_by_identity()

    def node_ids_by_identity(self):
        return self._node_ids_by_identity

    def get_node(self, node_id):
        try:
            return self.nodes[node_id]
        except KeyError as exc:
            raise ValueError(f"Catalog node '{node_id}' is not in this session") from exc

    def require_snapshot(self):
        if self.snapshot is None:
            raise ValueError("Build a file catalog before starting recovery")
        return self.snapshot
