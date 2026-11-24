from dataclasses import dataclass


@dataclass(frozen=True)
class PartitionScanRequestDto:
    disk_number: int
    deep_scan: bool = False
    resume: bool = False

    @classmethod
    def from_payload(cls, payload):
        disk_number = payload.get("diskNumber")
        deep_scan = payload.get("deepScan", False)
        resume = payload.get("resume", False)
        if isinstance(disk_number, bool):
            raise ValueError("diskNumber must be an integer")
        try:
            disk_number = int(disk_number)
        except (TypeError, ValueError) as exc:
            raise ValueError("diskNumber must be an integer") from exc
        if disk_number < 0:
            raise ValueError("diskNumber cannot be negative")
        if not isinstance(deep_scan, bool):
            raise ValueError("deepScan must be a boolean")
        if not isinstance(resume, bool):
            raise ValueError("resume must be a boolean")
        if resume and not deep_scan:
            raise ValueError("resume requires deepScan")
        return cls(disk_number, deep_scan, resume)
