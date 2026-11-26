import sys
import threading
from contextlib import contextmanager


class RecoverySession:
    MAX_RAW_CARVING_CHECKPOINT_BYTES = 8 * 1024 * 1024
    RAW_CHECKPOINT_BASE_BYTES = 1024
    RAW_CANDIDATE_REFERENCE_BYTES = 384

    def __init__(self):
        self.volumes = {}
        self.volume_source_ids = {}
        self.snapshot = None
        self.nodes = {}
        self._node_ids_by_identity = {}
        self._raw_carving_checkpoints = {}
        self._raw_carving_checkpoint_bytes = 0
        self._completed_raw_catalog_identity = None
        self._completed_raw_catalog = None
        self._raw_carving_lock = threading.RLock()

    @contextmanager
    def raw_carving_operation(self):
        """Serialize raw catalog builds so one session cursor has one writer."""
        with self._raw_carving_lock:
            yield

    def load_raw_carving_checkpoint(self, owner_key, identity_key):
        """Return an exact-identity checkpoint and release stale state for its volume."""
        with self._raw_carving_lock:
            entry = self._raw_carving_checkpoints.get(owner_key)
            if entry is None:
                return None
            stored_identity, checkpoint, _size_bytes = entry
            if stored_identity != identity_key:
                self._remove_raw_carving_checkpoint(owner_key)
                return None
            return checkpoint

    def validate_raw_carving_checkpoint_capacity(self, owner_key, identity_key, checkpoint):
        """Fail before replacing a usable checkpoint when the session budget is full."""
        if checkpoint is None:
            return
        required_bytes = self._estimate_raw_checkpoint_bytes(
            owner_key, identity_key, checkpoint,
        )
        with self._raw_carving_lock:
            old_entry = self._raw_carving_checkpoints.get(owner_key)
            old_bytes = old_entry[2] if old_entry is not None else 0
            total_bytes = self._raw_carving_checkpoint_bytes - old_bytes + required_bytes
            if total_bytes > self.MAX_RAW_CARVING_CHECKPOINT_BYTES:
                raise RuntimeError(
                    "Raw carving session checkpoint memory limit reached "
                    f"({total_bytes} of {self.MAX_RAW_CARVING_CHECKPOINT_BYTES} bytes). "
                    "The last valid checkpoint was preserved; reduce the candidate "
                    "limit or finish this session before retrying."
                )

    def save_raw_carving_checkpoint(self, owner_key, identity_key, checkpoint):
        """Replace or release a raw checkpoint without writing it to disk."""
        with self._raw_carving_lock:
            if checkpoint is None:
                self._remove_raw_carving_checkpoint(owner_key)
                return

            required_bytes = self._estimate_raw_checkpoint_bytes(
                owner_key, identity_key, checkpoint,
            )
            old_entry = self._raw_carving_checkpoints.get(owner_key)
            old_bytes = old_entry[2] if old_entry is not None else 0
            total_bytes = self._raw_carving_checkpoint_bytes - old_bytes + required_bytes
            if total_bytes > self.MAX_RAW_CARVING_CHECKPOINT_BYTES:
                raise RuntimeError(
                    "Raw carving session checkpoint memory limit reached "
                    f"({total_bytes} of {self.MAX_RAW_CARVING_CHECKPOINT_BYTES} bytes). "
                    "The last valid checkpoint was preserved; reduce the candidate "
                    "limit or finish this session before retrying."
                )

            self._raw_carving_checkpoints[owner_key] = (
                identity_key, checkpoint, required_bytes,
            )
            self._raw_carving_checkpoint_bytes = total_bytes

    @property
    def raw_carving_checkpoint_memory_bytes(self):
        """Return accounted bytes from a conservative checkpoint-size estimate."""
        with self._raw_carving_lock:
            return self._raw_carving_checkpoint_bytes

    def clear_raw_carving_checkpoints(self):
        """Release all in-memory raw resume state for this backend session."""
        with self._raw_carving_lock:
            self._raw_carving_checkpoints.clear()
            self._raw_carving_checkpoint_bytes = 0

    def get_completed_raw_catalog(self, identity_key):
        """Reuse a complete raw catalog only for the exact same scan identity."""
        with self._raw_carving_lock:
            if self._completed_raw_catalog_identity != identity_key:
                self._completed_raw_catalog_identity = None
                self._completed_raw_catalog = None
                return None
            return self._completed_raw_catalog

    def save_completed_raw_catalog(self, identity_key, snapshot):
        """Retain the completed catalog snapshot for repeated build requests."""
        with self._raw_carving_lock:
            self._completed_raw_catalog_identity = identity_key
            self._completed_raw_catalog = snapshot

    def clear_completed_raw_catalog(self):
        """Release a completed raw catalog when a different scan is requested."""
        with self._raw_carving_lock:
            self._completed_raw_catalog_identity = None
            self._completed_raw_catalog = None

    def _remove_raw_carving_checkpoint(self, owner_key):
        entry = self._raw_carving_checkpoints.pop(owner_key, None)
        if entry is not None:
            self._raw_carving_checkpoint_bytes -= entry[2]

    @classmethod
    def _estimate_raw_checkpoint_bytes(cls, owner_key, identity_key, checkpoint):
        owner_bytes = sum(
            sys.getsizeof(value) for value in owner_key
        ) if isinstance(owner_key, tuple) else sys.getsizeof(owner_key)
        return (
            cls.RAW_CHECKPOINT_BASE_BYTES
            + owner_bytes
            + sys.getsizeof(identity_key)
            + len(checkpoint.candidates) * cls.RAW_CANDIDATE_REFERENCE_BYTES
            + len(checkpoint.signature_carry)
        )

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
