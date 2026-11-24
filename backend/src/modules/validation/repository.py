from typing import Protocol

from modules.storage.entities import PhysicalDisk


class ValidationSnapshotRepository(Protocol):
    def load_validation_snapshot(self, disk: PhysicalDisk) -> dict | None: ...

    def save_validation_snapshot(self, disk: PhysicalDisk, snapshot: dict) -> dict | None: ...

    def invalidate_validation_snapshot(self, disk: PhysicalDisk) -> None: ...
