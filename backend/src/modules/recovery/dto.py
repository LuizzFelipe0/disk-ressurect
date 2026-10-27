from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryRequestDto:
    selected_node_ids: tuple[str, ...]
    excluded_node_ids: tuple[str, ...]
    output_directory: str
    extensions: tuple[str, ...]
    minimum_size_kb: int

    @classmethod
    def from_payload(cls, payload):
        selected = payload.get("selectedNodeIds", [])
        excluded = payload.get("excludedNodeIds", [])
        extensions = payload.get("extensions", [])
        output_directory = payload.get("outputDirectory", "")
        minimum_size = payload.get("minimumSizeKb", 0)
        for field_name, value in (("selectedNodeIds", selected), ("excludedNodeIds", excluded), ("extensions", extensions)):
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ValueError(f"{field_name} must be a list of strings")
        if not isinstance(output_directory, str):
            raise ValueError("outputDirectory must be a string")
        if isinstance(minimum_size, bool):
            raise ValueError("minimumSizeKb must be a non-negative integer")
        try:
            minimum_size = int(minimum_size)
        except (TypeError, ValueError) as exc:
            raise ValueError("minimumSizeKb must be a non-negative integer") from exc
        if minimum_size < 0:
            raise ValueError("minimumSizeKb must be a non-negative integer")
        return cls(tuple(selected), tuple(excluded), output_directory, tuple(extensions), minimum_size)


@dataclass(frozen=True)
class RecoveryResultDto:
    recovered_count: int
    candidate_count: int

    def to_dict(self):
        return {
            "recoveredCount": self.recovered_count,
            "candidateCount": self.candidate_count,
        }
