class NTFSContentReferenceStore:
    """Keep compact NTFS content locations behind opaque candidate references."""

    def __init__(self):
        self._references = {}

    def begin_catalog(self):
        self._references.clear()

    def register(self, reference_id, source, volume, file_node):
        record = getattr(file_node, "record", None)
        if record is not None:
            file_node = _CompactContentNode(record)
        self._references[str(reference_id)] = (source, volume, file_node)

    def resolve(self, reference_id):
        try:
            return self._references[str(reference_id)]
        except KeyError as exc:
            raise ValueError("Content reference is no longer available in this session") from exc


class _CompactContentRecord:
    """Retain only the fields needed to read a candidate during extraction."""

    __slots__ = (
        "file_size", "data_is_complete", "resident_data", "data_runs",
        "is_metadata_consistent", "data_extent_resolution",
        "data_extent_count", "data_extent_resolution_reason",
    )

    def __init__(self, record):
        self.file_size = int(getattr(record, "file_size", 0))
        self.data_is_complete = bool(getattr(record, "data_is_complete", True))
        resident_data = getattr(record, "resident_data", None)
        self.resident_data = None if resident_data is None else bytes(resident_data)
        self.data_runs = tuple(tuple(run) for run in (getattr(record, "data_runs", ()) or ()))
        self.is_metadata_consistent = getattr(record, "is_metadata_consistent", None)
        self.data_extent_resolution = getattr(record, "data_extent_resolution", None)
        self.data_extent_count = getattr(record, "data_extent_count", None)
        self.data_extent_resolution_reason = getattr(record, "data_extent_resolution_reason", None)


class _CompactContentNode:
    __slots__ = ("record",)

    def __init__(self, record):
        self.record = _CompactContentRecord(record)
