class NTFSContentReferenceStore:
    """Keep NTFS-specific content locations behind opaque candidate references."""

    def __init__(self):
        self._references = {}

    def begin_catalog(self):
        self._references.clear()

    def register(self, reference_id, source, volume, file_node):
        self._references[str(reference_id)] = (source, volume, file_node)

    def resolve(self, reference_id):
        try:
            return self._references[str(reference_id)]
        except KeyError as exc:
            raise ValueError("Content reference is no longer available in this session") from exc
