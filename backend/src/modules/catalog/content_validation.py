import os
from dataclasses import dataclass

from infrastructure.filesystems.ntfs.readers.file_signature_validator import FileSignatureValidator


@dataclass(frozen=True)
class CandidateContentValidation:
    """Bounded signature evidence gathered while building the catalog."""

    status: str
    reason: str


class CatalogContentValidator:
    """Check only the header window; full file/container validation stays in extraction."""

    def __init__(self, disk, volume_start, volume_end, cluster_size):
        self.disk = disk
        self.volume_start = int(volume_start)
        self.volume_end = int(volume_end)
        self.cluster_size = int(cluster_size)

    def validate(self, record):
        extension = self._extension(record.name)
        if extension not in FileSignatureValidator.supported_extensions():
            return CandidateContentValidation("unsupported", "No signature rule is available")
        if not getattr(record, "data_is_complete", True):
            return CandidateContentValidation("incomplete_metadata", "MFT data attributes are incomplete")

        size = int(record.file_size)
        if size <= 0:
            return CandidateContentValidation("invalid_size", "File has no content bytes")
        window_size = min(size, FileSignatureValidator.header_window(extension))
        try:
            header = self._read_prefix(record, window_size)
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            return CandidateContentValidation("unavailable", str(exc))

        if len(header) != window_size:
            return CandidateContentValidation("unavailable", "File data runs ended before the signature window")
        if not FileSignatureValidator.matches(extension, header):
            return CandidateContentValidation("signature_mismatch", "File header does not match its extension")
        return CandidateContentValidation("signature_match", "File header matches its extension")

    def _read_prefix(self, record, size):
        resident_data = getattr(record, "resident_data", None)
        if resident_data is not None:
            return bytes(resident_data[:size])

        runs = tuple(getattr(record, "data_runs", ()))
        if not runs:
            raise ValueError("No data runs are available")
        if self.cluster_size <= 0:
            raise ValueError("Invalid NTFS cluster size")

        header = bytearray()
        remaining = size
        for lcn, cluster_count in runs:
            if remaining <= 0:
                break
            cluster_count = int(cluster_count)
            if cluster_count <= 0:
                raise ValueError("A data run has a non-positive length")
            run_size = min(cluster_count * self.cluster_size, remaining)
            if lcn is None:
                header.extend(bytes(run_size))
            else:
                run_start = self.volume_start + int(lcn) * self.cluster_size
                run_end = run_start + run_size
                if run_start < self.volume_start or run_end > self.volume_end:
                    raise ValueError("A file data run is outside the selected volume")
                chunk = self.disk.read_at(run_start, run_size)
                if len(chunk) != run_size:
                    raise OSError(f"Short header read at {run_start:#x}: {len(chunk)} of {run_size} bytes")
                header.extend(chunk)
            remaining -= run_size
        return bytes(header)

    @staticmethod
    def _extension(name):
        return os.path.splitext(str(name))[1].casefold()
