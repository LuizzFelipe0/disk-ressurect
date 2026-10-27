from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from modules.disk_discovery.models import CachedDeepScan
from disk.models import NTFSVolume
from disk.scanning.partition_scan import ScanCheckpoint


class JsonDeepScanRepository:
    """Store complete NTFS volume metadata keyed by physical disk identity."""

    VERSION = 1

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self._memory = {}

    @staticmethod
    def disk_key(disk):
        serial = str(getattr(disk, "serial_number", "") or "").strip().casefold()
        identity = [
            str(getattr(disk, "model", "") or "").strip().casefold(),
            int(disk.size_bytes),
            serial,
        ]
        # Without a serial number, include the current device number to avoid
        # reusing a same-model/same-size disk's cached offsets by mistake.
        if not serial:
            identity.append(int(disk.number))
        digest = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode("utf-8"))
        return digest.hexdigest()

    def load(self, disk):
        entry = self._entries().get(self.disk_key(disk))
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
        if self.path is None:
            self._memory[key] = entry
            return CachedDeepScan(scanned_at=scanned_at, volumes=tuple(volumes), checkpoint=checkpoint)

        document = self._read_document()
        document["disks"][key] = entry
        self._write_document(document)
        return CachedDeepScan(scanned_at=scanned_at, volumes=tuple(volumes), checkpoint=checkpoint)

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

    def _read_document(self):
        if self.path is None or not self.path.exists():
            return {"version": self.VERSION, "disks": {}}
        try:
            with self.path.open("r", encoding="utf-8") as cache_file:
                document = json.load(cache_file)
        except (OSError, json.JSONDecodeError):
            return {"version": self.VERSION, "disks": {}}
        if (not isinstance(document, dict) or document.get("version") != self.VERSION
                or not isinstance(document.get("disks"), dict)):
            return {"version": self.VERSION, "disks": {}}
        return document

    def _write_document(self, document):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent,
                prefix=f"{self.path.name}.", suffix=".tmp", delete=False,
            ) as cache_file:
                temporary_path = Path(cache_file.name)
                json.dump(document, cache_file, ensure_ascii=False, separators=(",", ":"))
                cache_file.flush()
                os.fsync(cache_file.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()

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
