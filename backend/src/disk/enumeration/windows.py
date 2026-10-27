import json
import os
import subprocess
from typing import Callable

from disk.models import PhysicalDisk


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

    def __init__(self, runner: Callable = subprocess.run):
        self.runner = runner

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
            disks.append(PhysicalDisk(number, str(item.get("model") or "Unknown disk").strip(), size,
                                      str(item.get("serial") or "").strip()))
        return sorted(disks, key=lambda disk: disk.number)
