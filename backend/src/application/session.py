import sys
import threading
from contextlib import contextmanager
from dataclasses import replace


class RecoverySession:
    MAX_RAW_CARVING_CHECKPOINT_BYTES = 8 * 1024 * 1024
    MAX_RAW_SESSION_CANDIDATES = 16_384
    MAX_RAW_SESSION_RETAINED_BYTES = 512 * 1024 * 1024
    RAW_CHECKPOINT_BASE_BYTES = 1024

    def __init__(self):
        self.volumes = {}
        self.volume_source_ids = {}
        self.snapshot = None
        self.nodes = {}
        self._node_ids_by_identity = {}
        self._raw_carving_checkpoints = {}
        self._raw_carving_checkpoint_bytes = 0
        self._raw_catalogs = {}
        self._raw_generation = 0
        self._raw_carving_lock = threading.RLock()

    @contextmanager
    def raw_carving_operation(self):
        """Serialize raw catalog builds so one session cursor has one writer."""
        with self._raw_carving_lock:
            yield

    def load_raw_carving_checkpoint(self, owner_key, identity_key):
        """Return a cursor only when it matches the committed catalog generation."""
        with self._raw_carving_lock:
            checkpoint_entry = self._raw_carving_checkpoints.get(owner_key)
            catalog_entry = self._raw_catalogs.get(owner_key)
            if checkpoint_entry is None or catalog_entry is None:
                return None
            stored_identity, checkpoint, _size_bytes, generation = checkpoint_entry
            catalog_identity, _snapshot, catalog_generation, _count, _retained = catalog_entry
            if (stored_identity != identity_key or catalog_identity != identity_key
                    or generation != catalog_generation):
                return None
            return checkpoint

    def get_raw_catalog(self, owner_key, identity_key):
        """Return the last published raw catalog for a compatible scan identity."""
        with self._raw_carving_lock:
            entry = self._raw_catalogs.get(owner_key)
            if entry is None or entry[0] != identity_key:
                return None
            return entry[1]

    def raw_catalog_generation(self, owner_key, identity_key):
        with self._raw_carving_lock:
            entry = self._raw_catalogs.get(owner_key)
            return entry[2] if entry is not None and entry[0] == identity_key else None

    def raw_catalog_capacity(self, owner_key):
        """Return candidate and payload capacity after accounting for other volumes."""
        with self._raw_carving_lock:
            other_entries = (
                entry for key, entry in self._raw_catalogs.items() if key != owner_key
            )
            other_candidates = 0
            other_retained_bytes = 0
            for entry in other_entries:
                other_candidates += entry[3]
                other_retained_bytes += entry[4]
            return (
                max(0, self.MAX_RAW_SESSION_CANDIDATES - other_candidates),
                max(0, self.MAX_RAW_SESSION_RETAINED_BYTES - other_retained_bytes),
            )

    def commit_raw_catalog_generation(
        self, owner_key, identity_key, snapshot, checkpoint, content_reference_store,
    ):
        """Atomically publish the candidate catalog, cursor and content references."""
        candidate_count, retained_bytes = self.raw_catalog_candidate_metrics(snapshot)
        if (candidate_count > self.MAX_RAW_SESSION_CANDIDATES
                or retained_bytes > self.MAX_RAW_SESSION_RETAINED_BYTES):
            raise RuntimeError(
                "Raw session candidate limit exceeded; the previous catalog generation was preserved."
            )

        # Raw checkpoints contain cursor state only. Candidate references are
        # reconstructed transiently from the matching committed catalog.
        cursor = None if checkpoint is None else replace(checkpoint, candidates=())
        required_bytes = (
            self._estimate_raw_checkpoint_bytes(owner_key, identity_key, cursor)
            if cursor is not None else 0
        )
        with self._raw_carving_lock:
            old_entry = self._raw_carving_checkpoints.get(owner_key)
            old_bytes = old_entry[2] if old_entry is not None else 0
            total_checkpoint_bytes = (
                self._raw_carving_checkpoint_bytes - old_bytes + required_bytes
            )
            if total_checkpoint_bytes > self.MAX_RAW_CARVING_CHECKPOINT_BYTES:
                raise RuntimeError(
                    "Raw carving session checkpoint limit reached; "
                    "the previous catalog generation was preserved."
                )

            remaining_candidates, remaining_retained_bytes = self.raw_catalog_capacity(
                owner_key,
            )
            if (candidate_count > remaining_candidates
                    or retained_bytes > remaining_retained_bytes):
                raise RuntimeError(
                    "Raw session candidate or retained-data limit reached; "
                    "the previous catalog generation was preserved."
                )

            generation = self._raw_generation + 1
            other_catalogs = {
                key: entry for key, entry in self._raw_catalogs.items() if key != owner_key
            }
            checkpoints = {
                key: entry for key, entry in self._raw_carving_checkpoints.items()
                if key != owner_key
            }
            if cursor is not None:
                checkpoints[owner_key] = (
                    identity_key, cursor, required_bytes, generation,
                )
            catalogs = {
                **other_catalogs,
                owner_key: (
                    identity_key, snapshot, generation, candidate_count, retained_bytes,
                ),
            }
            checkpoint_bytes = sum(entry[2] for entry in checkpoints.values())
            # Commit the staged resolver before publishing the matching session
            # generation. All allocations and capacity checks have already passed.
            content_reference_store.commit_catalog()
            self._raw_carving_checkpoints = checkpoints
            self._raw_carving_checkpoint_bytes = checkpoint_bytes
            self._raw_catalogs = catalogs
            self._raw_generation = generation

    def update_raw_catalog_snapshot(self, owner_key, identity_key, expected_snapshot,
                                    snapshot):
        """Publish bounded cache-validation accounting for the current generation."""
        candidate_count, retained_bytes = self.raw_catalog_candidate_metrics(snapshot)
        with self._raw_carving_lock:
            entry = self._raw_catalogs.get(owner_key)
            if (entry is None or entry[0] != identity_key or entry[1] is not expected_snapshot):
                raise RuntimeError("Raw catalog generation changed during cache validation")
            remaining_candidates, remaining_retained_bytes = self.raw_catalog_capacity(owner_key)
            if (candidate_count > remaining_candidates
                    or retained_bytes > remaining_retained_bytes):
                raise RuntimeError(
                    "Raw session limit reached while accounting cache validation; "
                    "the previous catalog generation was preserved."
                )
            self._raw_catalogs[owner_key] = (
                entry[0], snapshot, entry[2], candidate_count, retained_bytes,
            )
            if self.snapshot is expected_snapshot:
                self.snapshot = snapshot
                self.nodes = snapshot.catalog.nodes

    @staticmethod
    def raw_catalog_candidate_metrics(snapshot):
        candidate_count = 0
        retained_bytes = 0
        for node in snapshot.catalog.nodes.values():
            candidate = node.candidate
            if candidate is None or not (
                {"content_carving", "fragment_reconstruction"}
                & set(candidate.discovery_methods)
            ):
                continue
            candidate_count += 1
            retained_bytes += int(candidate.size_bytes or 0)
        progress = getattr(snapshot, "png_recovery_progress", None)
        if progress is not None:
            retained_bytes += progress.estimated_retained_bytes
        return candidate_count, retained_bytes

    @property
    def raw_carving_checkpoint_memory_bytes(self):
        """Return accounted bytes from the cursor-only checkpoint estimate."""
        with self._raw_carving_lock:
            return self._raw_carving_checkpoint_bytes

    @property
    def raw_catalog_candidate_count(self):
        with self._raw_carving_lock:
            return sum(entry[3] for entry in self._raw_catalogs.values())

    @property
    def raw_catalog_retained_bytes(self):
        with self._raw_carving_lock:
            return sum(entry[4] for entry in self._raw_catalogs.values())

    def clear_raw_carving_state(self):
        """Release all raw cursors and candidate catalogs for this backend session."""
        with self._raw_carving_lock:
            self._raw_carving_checkpoints.clear()
            self._raw_carving_checkpoint_bytes = 0
            self._raw_catalogs.clear()

    @classmethod
    def _estimate_raw_checkpoint_bytes(cls, owner_key, identity_key, checkpoint):
        owner_bytes = sum(
            sys.getsizeof(value) for value in owner_key
        ) if isinstance(owner_key, tuple) else sys.getsizeof(owner_key)
        return (
            cls.RAW_CHECKPOINT_BASE_BYTES
            + owner_bytes
            + sys.getsizeof(identity_key)
            + len(checkpoint.signature_carry)
            + sys.getsizeof(checkpoint.png_signature_offsets)
            + sum(sys.getsizeof(value) for value in checkpoint.png_signature_offsets)
            + sys.getsizeof(checkpoint.png_signature_set_truncated)
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
        with self._raw_carving_lock:
            if not any(entry[1] is snapshot for entry in self._raw_catalogs.values()):
                self._raw_carving_checkpoints.clear()
                self._raw_carving_checkpoint_bytes = 0
                self._raw_catalogs.clear()
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
