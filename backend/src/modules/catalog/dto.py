from dataclasses import dataclass


@dataclass(frozen=True)
class VolumeSelectionRequestDto:
    volume_id: str

    @classmethod
    def from_payload(cls, payload):
        value = payload.get("volumeId")
        if not isinstance(value, str) or not value:
            raise ValueError("volumeId must be a non-empty string")
        return cls(value)


@dataclass(frozen=True)
class CatalogNodeRequestDto:
    node_id: str

    @classmethod
    def from_payload(cls, payload):
        value = payload.get("nodeId")
        if not isinstance(value, str) or not value:
            raise ValueError("nodeId must be a non-empty string")
        return cls(value)


@dataclass(frozen=True)
class CatalogNodeDto:
    id: str
    name: str
    path: str
    is_directory: bool
    size_bytes: int
    has_children: bool

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "isDirectory": self.is_directory,
            "sizeBytes": self.size_bytes,
            "hasChildren": self.has_children,
        }


@dataclass(frozen=True)
class CatalogDto:
    record_count: int
    available_extensions: tuple[str, ...]
    roots: tuple[CatalogNodeDto, ...]

    def to_dict(self):
        return {
            "recordCount": self.record_count,
            "availableExtensions": list(self.available_extensions),
            "roots": [node.to_dict() for node in self.roots],
        }
