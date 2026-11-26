import json
import os
import subprocess
from typing import Callable

from modules.storage.entities import PhysicalDisk


class WindowsDiskEnumerator:
    """List physical disks using the Windows storage inventory provider."""

    POWERSHELL_COMMAND = (
        "$ErrorActionPreference='Stop'; "
        "Get-CimInstance Win32_DiskDrive | "
        "Select-Object @{Name='number';Expression={$_.Index}}, "
        "@{Name='model';Expression={$_.Model}}, "
        "@{Name='size';Expression={[Int64]$_.Size}}, "
        "@{Name='serial';Expression={$_.SerialNumber}} | "
        "ConvertTo-Json -Compress"
    )

    def __init__(self, runner: Callable = subprocess.run, raw_disk_factory=None):
        self.runner = runner
        self.raw_disk_factory = raw_disk_factory

    def list_disks(self):
        if os.name != "nt":
            raise OSError("Physical disk inventory is currently supported on Windows only")
        command = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", self.POWERSHELL_COMMAND]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = self.runner(command, capture_output=True, text=True, timeout=30, creationflags=flags)
        if result.returncode:
            detail = result.stderr.strip() or "Windows storage inventory query failed"
            raise OSError(detail)
        payload = json.loads(result.stdout or "[]")
        if isinstance(payload, dict):
            payload = [payload]
        disks = []
        for item in payload:
            try:
                number = int(item["number"])
                size = int(item["size"])
            except (KeyError, TypeError, ValueError):
                continue
            if number < 0 or size <= 0:
                continue
            accessible_size = self._read_accessible_size(number)
            disks.append(PhysicalDisk(
                number,
                str(item.get("model") or "Unknown disk").strip(),
                accessible_size if accessible_size is not None else size,
                str(item.get("serial") or "").strip(),
                identity_size_bytes=size,
            ))
        return sorted(disks, key=lambda disk: disk.number)

    def _read_accessible_size(self, number):
        """Use the raw reader's geometry when available; retain WMI as identity metadata."""
        reader_factory = self.raw_disk_factory
        if reader_factory is None:
            from infrastructure.disk.windows.reader import RawDisk
            reader_factory = RawDisk
        try:
            reader = reader_factory(number)
        except OSError:
            # Disk inventory must remain available before elevation. Once the
            # reader is accessible, its geometry becomes the canonical capacity.
            return None
        try:
            size = int(getattr(reader, "size_bytes", getattr(reader, "size", 0)))
            return size if size > 0 else None
        finally:
            reader.close()
