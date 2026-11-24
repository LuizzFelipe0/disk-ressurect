"""Persistable cursor and candidate references for resumable content carving."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CarvedCandidateReference:
    """Identity of one previously validated candidate, without its file bytes."""

    offset: int
    extension: str
    size_bytes: int
    sha256: str

    def __post_init__(self):
        if self.offset < 0 or self.size_bytes <= 0:
            raise ValueError("Candidate offset and size must be positive")
        if not self.extension.startswith(".") or len(self.extension) > 16:
            raise ValueError("Candidate extension is invalid")
        if len(self.sha256) != 64 or any(character not in "0123456789abcdef" for character in self.sha256):
            raise ValueError("Candidate digest must be a lowercase SHA-256 hex string")


@dataclass(frozen=True)
class CarvingCheckpoint:
    """Resume position for one bounded scan of normalized physical ranges.

    ``range_fingerprint`` records the full range set while
    ``processed_range_fingerprint`` binds the cursor to its consumed prefix.
    Candidate references let callers restore earlier results by rereading and
    revalidating only those candidate extents, rather than scanning old ranges.
    """

    range_fingerprint: str
    range_index: int
    next_offset: int
    disk_size: int
    bytes_per_sector: int
    scan_profile: str
    candidates: tuple[CarvedCandidateReference, ...] = ()
    bytes_scanned: int = 0
    signature_carry: bytes = b""
    processed_range_fingerprint: str = ""

    def __post_init__(self):
        if len(self.range_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in self.range_fingerprint
        ):
            raise ValueError("Range fingerprint must be a lowercase SHA-256 hex string")
        if self.processed_range_fingerprint and (
            len(self.processed_range_fingerprint) != 64 or any(
                character not in "0123456789abcdef"
                for character in self.processed_range_fingerprint
            )
        ):
            raise ValueError("Processed range fingerprint must be a lowercase SHA-256 hex string")
        if self.range_index < 0 or self.next_offset < 0 or self.disk_size <= 0:
            raise ValueError("Carving checkpoint position is invalid")
        if self.bytes_per_sector <= 0 or self.bytes_scanned < 0:
            raise ValueError("Carving checkpoint geometry is invalid")
        if not self.scan_profile:
            raise ValueError("Carving checkpoint scan profile is required")
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "signature_carry", bytes(self.signature_carry))
        if len(self.signature_carry) > 32:
            raise ValueError("Signature carry exceeds the supported signature overlap")
        if any(not isinstance(item, CarvedCandidateReference) for item in self.candidates):
            raise TypeError("Carving checkpoint candidates must be candidate references")
