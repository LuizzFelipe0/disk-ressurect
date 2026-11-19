from dataclasses import dataclass


@dataclass(frozen=True)
class CarvedContentRecord:
    """Catalog-facing candidate with bytes found outside filesystem metadata."""

    index: int
    offset: int
    name: str
    resident_data: bytes
    cluster_allocation_status: str = "free"
    sequence_number: int = 0
    is_valid: bool = True
    # Raw carving cannot prove this file was deleted; do not label it as such.
    is_allocated: bool = True
    is_dir: bool = False
    file_size: int = 0
    data_is_complete: bool = True
    data_runs: tuple = ()
    raw_data: bytes = b""
    catalog_content_validation: str = "format_structure_match"
    catalog_content_validation_reason: str = (
        "Contiguous file structure and format markers passed validation"
    )

    def __post_init__(self):
        data = bytes(self.resident_data)
        object.__setattr__(self, "resident_data", data)
        object.__setattr__(self, "file_size", len(data))
