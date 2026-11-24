from infrastructure.filesystems.ntfs.readers.file_content_reader import (
    FileContentError,
    NTFSFileContentReader,
)
from modules.recovery.entities import ContentReadError


class NTFSContentReferenceReader:
    """Resolve an opaque candidate handle and stream NTFS data on demand."""

    def __init__(self, reader_factory, reference_store):
        self.reader_factory = reader_factory
        self.reference_store = reference_store

    def iter_chunks(self, reference):
        source, volume, file_node = self.reference_store.resolve(reference.reference_id)
        if source.source_id != reference.source_id:
            raise ValueError("Content source identity no longer matches the candidate")
        disk = self.reader_factory(source)
        try:
            validate_source = getattr(disk, "validate_source", None)
            if validate_source is not None and validate_source() != reference.source_id:
                raise ValueError("Storage source changed since the catalog was built")
            content_reader = NTFSFileContentReader(
                disk,
                volume.partition_offset,
                volume.cluster_size,
                volume_size_bytes=volume.partition_size,
            )
            try:
                yield from content_reader.iter_chunks(file_node)
            except FileContentError as exc:
                raise ContentReadError(exc.status, exc.reason) from exc
        finally:
            disk.close()
