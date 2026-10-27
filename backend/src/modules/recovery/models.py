from dataclasses import dataclass


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
