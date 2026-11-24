from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from infrastructure.disk.inventory import DiskInventory
from infrastructure.persistence.deep_scan_repository import JsonDeepScanRepository
from modules.catalog.service import CatalogService
from modules.disk.service import DiskDiscoveryService
from modules.recovery.service import RecoveryWorkflow
from presentation.controller import RecoveryCommandHandler
from presentation.transport import serve


def cache_path_for_data_directory(data_directory=None):
    directory = data_directory or default_data_directory()
    return os.path.join(os.fspath(directory), "deep_scan_cache.json")


def default_data_directory():
    configured = os.environ.get("DISK_RESURRECT_DATA_DIR")
    if configured:
        return Path(configured)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / "Disk Ressurect"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Disk Ressurect"
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "disk-ressurect"


def create_handler(cache_path=None, inventory=None, workflow=None, scan_repository=None):
    """Compose application services while keeping runtime dependencies replaceable."""
    if cache_path is None:
        cache_path = cache_path_for_data_directory()
    elif os.path.isdir(cache_path):
        cache_path = os.path.join(cache_path, "deep_scan_cache.json")
    discovery = DiskDiscoveryService(
        inventory=inventory if inventory is not None else DiskInventory(),
        scan_repository=(scan_repository if scan_repository is not None else JsonDeepScanRepository(cache_path)),
    )
    return RecoveryCommandHandler(
        discovery,
        CatalogService(),
        workflow if workflow is not None else RecoveryWorkflow(),
    )


def main():
    serve(create_handler())


if __name__ == "__main__":
    main()
