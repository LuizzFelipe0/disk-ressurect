from dataclasses import dataclass
import hashlib
import json
from typing import Literal

@dataclass(frozen=True)
class ExtractionResult:
    """Outcome for one file, shared by recovery services and reports."""

    node: object
    status: str
    reason: str
    bytes_written: int

    @property
    def path(self):
        return self.node.full_path


@dataclass(frozen=True)
class RecoveryProgress:
    stage: str
    completed: int
    total: int
    message: str = ""


@dataclass(frozen=True)
class ExtractionSummary:
    recovered_count: int
    results: tuple[ExtractionResult, ...]
    partial_exported_count: int = 0


CandidateDeletionState = Literal["deleted", "not_deleted", "unknown"]
CandidateAllocationState = Literal["free", "allocated", "mixed", "unknown"]
CandidateIntegrityState = Literal["validated", "partial", "invalid", "unknown"]
CandidateRecoverability = Literal["recoverable", "partial", "unavailable", "unknown"]


class ContentReadError(Exception):
    """Generic failure reported by a content-reference adapter."""

    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = str(status)
        self.reason = str(reason)


def stable_candidate_id(source_id, volume_id, logical_identity, size_bytes, content_sha256=None):
    """Build an opaque identity from semantic identity, never a scan offset or strategy."""
    source_id = str(source_id).strip()
    volume_id = str(volume_id).strip()
    logical_identity = str(logical_identity or "").strip().casefold()
    size_bytes = int(size_bytes)
    digest = str(content_sha256 or "").strip().casefold()
    if not source_id or not volume_id or size_bytes < 0:
        raise ValueError("Candidate source, volume and non-negative size are required")
    if not logical_identity and not digest:
        raise ValueError("Candidate needs a logical identity or content digest")
    if digest and (len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
        raise ValueError("Candidate content digest must be a SHA-256 hex value")
    identity = json.dumps(
        [source_id, volume_id, logical_identity, size_bytes, digest],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(identity).hexdigest()


@dataclass(frozen=True)
class RecoveryEvidence:
    kind: str
    origin: str
    details: tuple[tuple[str, str | int | bool | None], ...] = ()


@dataclass(frozen=True)
class ContentReference:
    """Opaque handle resolved by the source adapter; it contains no physical offsets."""

    reference_id: str
    source_id: str
    size_bytes: int
    sha256: str | None = None

    def __post_init__(self):
        if not self.reference_id or not self.source_id:
            raise ValueError("Content reference and source identities are required")
        if self.size_bytes < 0:
            raise ValueError("Content reference size cannot be negative")
        if self.sha256 is not None:
            digest = self.sha256.casefold()
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Content reference digest must be a SHA-256 hex value")
            object.__setattr__(self, "sha256", digest)


@dataclass(frozen=True)
class RecoveryCandidate:
    candidate_id: str
    source_id: str
    volume_id: str
    name: str | None
    original_path: str | None
    size_bytes: int | None
    filesystem_id: str | None
    discovery_methods: tuple[str, ...]
    evidence: tuple[RecoveryEvidence, ...]
    deletion_state: CandidateDeletionState = "unknown"
    allocation_state: CandidateAllocationState = "unknown"
    integrity_state: CandidateIntegrityState = "unknown"
    recoverability: CandidateRecoverability = "unknown"
    content_reference: ContentReference | None = None

    def __post_init__(self):
        if not self.candidate_id or not self.source_id or not self.volume_id:
            raise ValueError("Candidate, source and volume identities are required")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("Candidate size cannot be negative")
        object.__setattr__(self, "discovery_methods", tuple(self.discovery_methods))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if (self.content_reference is not None
                and self.content_reference.source_id != self.source_id):
            raise ValueError("Candidate content reference belongs to a different source")
