from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from modules.disk.entities import CachedDeepScan
from modules.disk.entities import NTFSVolume
from modules.deep_scan.entities import CarvedCandidateReference, CarvingCheckpoint
from modules.storage.entities import ScanCheckpoint
from infrastructure.filesystems.user_ownership import (
    ensure_pkexec_user_owned_directory,
    open_pkexec_safe_directory,
    set_pkexec_user_ownership_fd,
)
from infrastructure.disk.output_safety import volume_disk_numbers


class JsonDeepScanRepository:
    """Store complete NTFS volume metadata keyed by physical disk identity."""

    VERSION = 2
    MAX_VALIDATION_SNAPSHOT_BYTES = 32 * 1024 * 1024

    def __init__(self, path=None, disk_mapper=volume_disk_numbers):
        self.path = Path(path) if path else None
        self.disk_mapper = disk_mapper
        self._memory = {}
        self._carving_memory = {}
        self._validation_memory = {}

    @staticmethod
    def disk_key(disk):
        serial = str(getattr(disk, "serial_number", "") or "").strip().casefold()
        identity_size = getattr(disk, "identity_size_bytes", None)
        if identity_size is None:
            identity_size = disk.size_bytes
        identity = [
            str(getattr(disk, "model", "") or "").strip().casefold(),
            int(identity_size),
            serial,
        ]
        # Without a serial number, include the current device number to avoid
        # reusing a same-model/same-size disk's cached offsets by mistake.
        if not serial:
            identity.append(int(disk.number))
        digest = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode("utf-8"))
        return digest.hexdigest()

    def load(self, disk):
        key = self.disk_key(disk)
        entry = self._memory.get(key) if key in self._memory else self._entries().get(key)
        if not isinstance(entry, dict):
            return None
        scanned_at = entry.get("scannedAt")
        raw_volumes = entry.get("volumes")
        if not isinstance(scanned_at, str) or not isinstance(raw_volumes, list):
            return None
        try:
            volumes = tuple(self._deserialize_volume(item, int(disk.number)) for item in raw_volumes)
        except (KeyError, TypeError, ValueError):
            return None
        if any(not self._fits_disk(volume, int(disk.size_bytes)) for volume in volumes):
            return None
        checkpoint = self._deserialize_checkpoint(entry.get("checkpoint"))
        return CachedDeepScan(scanned_at=scanned_at, volumes=volumes, checkpoint=checkpoint)

    def save(self, disk, volumes, checkpoint=None):
        scanned_at = datetime.now(timezone.utc).isoformat()
        key = self.disk_key(disk)
        entry = {
            "scannedAt": scanned_at,
            "volumes": [self._serialize_volume(volume) for volume in volumes],
            "checkpoint": self._serialize_checkpoint(checkpoint),
        }
        if not self._can_persist_for(disk):
            self._memory[key] = entry
            return CachedDeepScan(scanned_at=scanned_at, volumes=tuple(volumes), checkpoint=checkpoint)

        document = self._read_document()
        document["version"] = self.VERSION
        document["disks"][key] = entry
        self._write_document(document)
        return CachedDeepScan(scanned_at=scanned_at, volumes=tuple(volumes), checkpoint=checkpoint)

    def load_carving_checkpoint(self, disk, volume):
        """Load the cursor only for the same disk and volume geometry."""
        disk_key = self.disk_key(disk)
        volume_key = self._carving_volume_key(volume)
        if self.path is None or not self._can_persist_for(disk):
            data = self._carving_memory.get((disk_key, volume_key))
        else:
            data = self._read_document().get("carving", {}).get(disk_key, {}).get(volume_key)
        checkpoint = self._deserialize_carving_checkpoint(data)
        if checkpoint is None:
            return None
        if (checkpoint.disk_size != int(disk.size_bytes)
                or checkpoint.bytes_per_sector != int(volume.bytes_per_sector)):
            return None
        return checkpoint

    def save_carving_checkpoint(self, disk, volume, checkpoint):
        """Persist compact carving state separately from lost-partition scans."""
        if checkpoint is not None and not isinstance(checkpoint, CarvingCheckpoint):
            raise TypeError("checkpoint must be a CarvingCheckpoint or None")
        disk_key = self.disk_key(disk)
        volume_key = self._carving_volume_key(volume)
        if self.path is None or not self._can_persist_for(disk):
            key = (disk_key, volume_key)
            if checkpoint is None:
                self._carving_memory.pop(key, None)
            else:
                self._carving_memory[key] = self._serialize_carving_checkpoint(checkpoint)
            return checkpoint

        document = self._read_document()
        document["version"] = self.VERSION
        carving = document.setdefault("carving", {})
        disk_entries = carving.setdefault(disk_key, {})
        if checkpoint is None:
            disk_entries.pop(volume_key, None)
            if not disk_entries:
                carving.pop(disk_key, None)
        else:
            disk_entries[volume_key] = self._serialize_carving_checkpoint(checkpoint)
        self._write_document(document)
        return checkpoint

    def load_validation_snapshot(self, disk):
        """Load the last bounded full-disk scan snapshot for this disk identity."""
        key = self.disk_key(disk)
        if self.path is None or key in self._validation_memory:
            snapshot = self._validation_memory.get(key)
        else:
            snapshot = self._read_document().get("validation", {}).get(key)
        if not isinstance(snapshot, dict):
            return None
        try:
            identity_matches = (
                snapshot.get("version") == 1
                and snapshot.get("identity") == self._disk_identity(disk)
                and int(snapshot.get("diskSize", -1)) == int(disk.size_bytes)
            )
        except (TypeError, ValueError, OverflowError):
            identity_matches = False
        if not identity_matches:
            return None
        try:
            if len(json.dumps(snapshot, separators=(",", ":")).encode("utf-8")) > self.MAX_VALIDATION_SNAPSHOT_BYTES:
                self.invalidate_validation_snapshot(disk)
                return None
        except (TypeError, ValueError):
            self.invalidate_validation_snapshot(disk)
            return None
        return snapshot

    def save_validation_snapshot(self, disk, snapshot):
        """Persist only the compact scan evidence and revalidation references."""
        if not isinstance(snapshot, dict):
            raise TypeError("snapshot must be a JSON object")
        key = self.disk_key(disk)
        if (snapshot.get("version") != 1
                or snapshot.get("identity") != self._disk_identity(disk)
                or int(snapshot.get("diskSize", -1)) != int(disk.size_bytes)):
            raise ValueError("Validation snapshot identity does not match the physical disk")
        try:
            encoded_size = len(json.dumps(snapshot, separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Validation snapshot must contain JSON-safe values") from exc
        if encoded_size > self.MAX_VALIDATION_SNAPSHOT_BYTES:
            self.invalidate_validation_snapshot(disk)
            return None
        if self.path is None or not self._can_persist_for(disk):
            self._validation_memory[key] = snapshot
            return snapshot
        document = self._read_document()
        document["version"] = self.VERSION
        document.setdefault("validation", {})[key] = snapshot
        self._write_document(document)
        return snapshot

    def invalidate_validation_snapshot(self, disk):
        """Remove evidence after identity, layout or metadata revalidation fails."""
        key = self.disk_key(disk)
        if self.path is None:
            self._validation_memory.pop(key, None)
            return
        if not self._can_persist_for(disk):
            # Keep a session-local tombstone so the unchanged on-disk cache is
            # not reused after its evidence has been rejected.
            self._validation_memory[key] = None
            return
        document = self._read_document()
        validation = document.setdefault("validation", {})
        if validation.pop(key, None) is not None:
            self._write_document(document)

    @staticmethod
    def _carving_volume_key(volume):
        return ":".join(str(int(value)) for value in (
            volume.partition_offset,
            volume.partition_size,
            volume.bytes_per_sector,
            volume.cluster_size,
        ))

    @staticmethod
    def _serialize_carving_checkpoint(checkpoint):
        return {
            "rangeFingerprint": checkpoint.range_fingerprint,
            "processedRangeFingerprint": checkpoint.processed_range_fingerprint,
            "rangeIndex": checkpoint.range_index,
            "nextOffset": checkpoint.next_offset,
            "diskSize": checkpoint.disk_size,
            "bytesPerSector": checkpoint.bytes_per_sector,
            "scanProfile": checkpoint.scan_profile,
            "bytesScanned": checkpoint.bytes_scanned,
            "signatureCarryHex": checkpoint.signature_carry.hex(),
            "candidates": [
                {
                    "offset": item.offset,
                    "extension": item.extension,
                    "sizeBytes": item.size_bytes,
                    "sha256": item.sha256,
                }
                for item in checkpoint.candidates
            ],
        }

    @staticmethod
    def _deserialize_carving_checkpoint(data):
        if not isinstance(data, dict):
            return None
        raw_candidates = data.get("candidates", [])
        if not isinstance(raw_candidates, list) or len(raw_candidates) > 10000:
            return None
        try:
            candidates = tuple(CarvedCandidateReference(
                offset=int(item["offset"]),
                extension=str(item["extension"]),
                size_bytes=int(item["sizeBytes"]),
                sha256=str(item["sha256"]),
            ) for item in raw_candidates if isinstance(item, dict))
            if len(candidates) != len(raw_candidates):
                return None
            return CarvingCheckpoint(
                range_fingerprint=str(data["rangeFingerprint"]),
                processed_range_fingerprint=str(data.get("processedRangeFingerprint", "")),
                range_index=int(data["rangeIndex"]),
                next_offset=int(data["nextOffset"]),
                disk_size=int(data["diskSize"]),
                bytes_per_sector=int(data["bytesPerSector"]),
                scan_profile=str(data["scanProfile"]),
                candidates=candidates,
                bytes_scanned=int(data.get("bytesScanned", 0)),
                signature_carry=bytes.fromhex(str(data.get("signatureCarryHex", ""))),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _serialize_checkpoint(checkpoint):
        if checkpoint is None:
            return None
        return {
            "rangeIndex": checkpoint.range_index,
            "nextOffset": checkpoint.next_offset,
            "diskSize": checkpoint.disk_size,
            "bytesPerSector": checkpoint.bytes_per_sector,
        }

    @staticmethod
    def _deserialize_checkpoint(data):
        if data is None:
            return None
        if not isinstance(data, dict):
            return None
        try:
            values = (
                int(data["rangeIndex"]), int(data["nextOffset"]),
                int(data["diskSize"]), int(data["bytesPerSector"]),
            )
            if any(value < 0 for value in values) or values[3] <= 0:
                return None
            return ScanCheckpoint(*values)
        except (KeyError, TypeError, ValueError):
            return None

    def _entries(self):
        if self.path is None:
            return self._memory
        return self._read_document()["disks"]

    def _can_persist_for(self, disk):
        """Never write scan state onto the physical source or an unknown device."""
        if self.path is None or int(getattr(disk, "number", -1)) < 0:
            return False
        try:
            return int(disk.number) not in self.disk_mapper(self.path.parent)
        except (OSError, ValueError, TypeError):
            return False

    def _read_document(self):
        if self.path is None:
            return {"version": self.VERSION, "disks": {}, "carving": {}, "validation": {}}
        descriptor = None
        try:
            if sys.platform.startswith("linux") and os.open in os.supports_dir_fd:
                directory_fd = open_pkexec_safe_directory(self.path.parent)
                try:
                    descriptor = os.open(
                        self.path.name,
                        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=directory_fd,
                    )
                finally:
                    os.close(directory_fd)
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    return {"version": self.VERSION, "disks": {}, "carving": {}, "validation": {}}
                with os.fdopen(descriptor, "r", encoding="utf-8") as cache_file:
                    descriptor = None
                    document = json.load(cache_file)
            else:
                if not self.path.exists():
                    return {"version": self.VERSION, "disks": {}, "carving": {}, "validation": {}}
                with self.path.open("r", encoding="utf-8") as cache_file:
                    document = json.load(cache_file)
        except (OSError, json.JSONDecodeError):
            return {"version": self.VERSION, "disks": {}, "carving": {}, "validation": {}}
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if (not isinstance(document, dict) or document.get("version") not in (1, self.VERSION)
                or not isinstance(document.get("disks"), dict)):
            return {"version": self.VERSION, "disks": {}, "carving": {}, "validation": {}}
        if not isinstance(document.get("carving", {}), dict):
            document["carving"] = {}
        if not isinstance(document.get("validation", {}), dict):
            document["validation"] = {}
        document["version"] = self.VERSION
        return document

    @staticmethod
    def _disk_identity(disk):
        serial = str(getattr(disk, "serial_number", "") or "").strip().casefold()
        identity = {
            "model": str(getattr(disk, "model", "") or "").strip().casefold(),
            "sizeBytes": int(disk.size_bytes),
            "serialNumber": serial,
        }
        if not serial:
            identity["number"] = int(disk.number)
        return identity

    def _write_document(self, document):
        ensure_pkexec_user_owned_directory(self.path.parent)
        if not (sys.platform.startswith("linux") and os.open in os.supports_dir_fd):
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent,
                prefix=f"{self.path.name}.", suffix=".tmp", delete=False,
            ) as cache_file:
                temporary_path = Path(cache_file.name)
                json.dump(document, cache_file, ensure_ascii=False, separators=(",", ":"))
                cache_file.flush()
                os.fsync(cache_file.fileno())
                set_pkexec_user_ownership_fd(cache_file.fileno())
            try:
                os.replace(temporary_path, self.path)
            finally:
                if temporary_path.exists():
                    temporary_path.unlink()
            return

        temporary_name = None
        directory_fd = None
        try:
            directory_fd = open_pkexec_safe_directory(self.path.parent)
            for _ in range(32):
                temporary_name = f"{self.path.name}.{secrets.token_hex(12)}.tmp"
                try:
                    descriptor = os.open(
                        temporary_name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL
                        | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                        0o600,
                        dir_fd=directory_fd,
                    )
                    break
                except FileExistsError:
                    continue
            else:
                raise FileExistsError("Could not allocate a unique scan-cache temporary file")

            with os.fdopen(descriptor, "w", encoding="utf-8") as cache_file:
                json.dump(document, cache_file, ensure_ascii=False, separators=(",", ":"))
                cache_file.flush()
                os.fsync(cache_file.fileno())
                set_pkexec_user_ownership_fd(cache_file.fileno())
            os.replace(temporary_name, self.path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        finally:
            if directory_fd is not None:
                if temporary_name:
                    try:
                        os.unlink(temporary_name, dir_fd=directory_fd)
                    except FileNotFoundError:
                        pass
                os.close(directory_fd)

    @staticmethod
    def _serialize_volume(volume):
        return {
            "disk_number": int(volume.disk_number),
            "partition_number": int(volume.partition_number),
            "partition_offset": int(volume.partition_offset),
            "partition_size": int(volume.partition_size),
            "bytes_per_sector": int(volume.bytes_per_sector),
            "cluster_size": int(volume.cluster_size),
            "record_size": int(volume.record_size),
            "mft_offset": int(volume.mft_offset),
            "mft_size": int(volume.mft_size),
            "mft_fragments": [list(fragment) for fragment in volume.mft_fragments],
            "partition_name": volume.partition_name,
            "partition_size_is_estimated": bool(volume.partition_size_is_estimated),
        }

    @staticmethod
    def _deserialize_volume(data, current_disk_number):
        fragments = tuple(tuple(int(value) for value in fragment) for fragment in data["mft_fragments"])
        if any(len(fragment) != 3 for fragment in fragments):
            raise ValueError("Invalid MFT fragment in deep-scan cache")
        return NTFSVolume(
            disk_number=current_disk_number,
            partition_number=int(data["partition_number"]),
            partition_offset=int(data["partition_offset"]),
            partition_size=int(data["partition_size"]),
            bytes_per_sector=int(data["bytes_per_sector"]),
            cluster_size=int(data["cluster_size"]),
            record_size=int(data["record_size"]),
            mft_offset=int(data["mft_offset"]),
            mft_size=int(data["mft_size"]),
            mft_fragments=fragments,
            partition_name=str(data.get("partition_name") or ""),
            partition_size_is_estimated=bool(data.get("partition_size_is_estimated", False)),
        )

    @staticmethod
    def _fits_disk(volume, disk_size):
        if (volume.partition_offset < 0 or volume.partition_size <= 0
                or volume.partition_offset + volume.partition_size > disk_size
                or volume.cluster_size <= 0 or volume.mft_offset < 0
                or volume.mft_size <= 0 or not volume.mft_fragments):
            return False
        return all(
            physical_offset >= volume.partition_offset
            and count > 0
            and base_index >= 0
            and physical_offset + count * volume.cluster_size <= disk_size
            for physical_offset, count, base_index in volume.mft_fragments
        )
