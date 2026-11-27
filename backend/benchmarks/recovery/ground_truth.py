"""Oracle-only ground-truth records for deterministic synthetic workloads."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json


@dataclass(frozen=True)
class GroundTruthEntry:
    file_id: str
    sha256: str
    size_bytes: int
    logical_ranges: tuple[tuple[int, int], ...]
    physical_ranges: tuple[tuple[int, int], ...]
    fragmentation: str
    allocation_evidence: str
    corruption_regions: tuple[tuple[int, int], ...]
    expected_recovery: str
    negative_reason: str | None = None

    @classmethod
    def original(cls, file_id, data, *, logical_ranges=(), physical_ranges=(),
                 fragmentation="contiguous", allocation_evidence="trusted_free",
                 corruption_regions=(), expected_recovery="contiguous_carving",
                 negative_reason=None):
        return cls(
            file_id=str(file_id),
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            logical_ranges=tuple(tuple(map(int, item)) for item in logical_ranges),
            physical_ranges=tuple(tuple(map(int, item)) for item in physical_ranges),
            fragmentation=str(fragmentation),
            allocation_evidence=str(allocation_evidence),
            corruption_regions=tuple(tuple(map(int, item)) for item in corruption_regions),
            expected_recovery=str(expected_recovery),
            negative_reason=negative_reason,
        )


@dataclass(frozen=True)
class GroundTruthManifest:
    seed: int
    workload: str
    size_bytes: int
    entries: tuple[GroundTruthEntry, ...]
    eligible_ranges: tuple[tuple[int, int], ...]
    excluded_ranges: tuple[tuple[int, int], ...]
    overwrite_regions: tuple[tuple[int, int], ...] = ()

    def serialize(self):
        return json.dumps(asdict(self), sort_keys=True, indent=2)
