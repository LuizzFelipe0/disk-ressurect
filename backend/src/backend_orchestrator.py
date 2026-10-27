from __future__ import annotations

import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(__file__))

from disk.inventory import DiskInventory
from infrastructure.persistence.deep_scan_repository import JsonDeepScanRepository
from modules.catalog.service import CatalogService
from modules.commands.controller import RecoveryCommandHandler
from modules.disk_discovery.service import DiskDiscoveryService
from modules.recovery.service import RecoveryWorkflow


def create_handler(cache_path=None, inventory=None, workflow=None, scan_repository=None):
    """Compose application services while keeping runtime dependencies replaceable."""
    if cache_path is None:
        data_directory = os.environ.get("DISK_RESURRECT_DATA_DIR")
        cache_path = os.path.join(data_directory, "deep_scan_cache.json") if data_directory else None
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
    handler = create_handler()
    write_lock = threading.Lock()
    operation_lock = threading.Lock()

    def emit(message):
        with write_lock:
            sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    emit({"type": "ready", "payload": {"message": "Python recovery service is ready"}})

    for line in sys.stdin:
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            emit({"id": None, "type": "error", "error": f"Invalid request: {exc}", "errorType": "ValueError"})
            continue
        if not operation_lock.acquire(blocking=False):
            request_id = request.get("id") if isinstance(request, dict) else None
            emit({"id": request_id, "type": "error", "error": "Another disk operation is already running",
                  "errorType": "BusyError"})
            continue

        def run(current_request=request):
            try:
                handler.handle(current_request, emit)
            finally:
                operation_lock.release()

        threading.Thread(target=run, name="recovery-command", daemon=True).start()


if __name__ == "__main__":
    main()
