"""JSON-lines adapter exposing the recovery workflow to desktop frontends.

The adapter keeps all disk and recovery logic in the existing Python services.
Each input line is one request; responses and progress events are written as
JSON lines to stdout. Diagnostic output must go to stderr.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback

sys.path.insert(0, os.path.dirname(__file__))

from application.recovery_workflow import RecoveryProgress, RecoveryWorkflow
from disk.inventory import DiskInventory
from ntfs.extractor import Extractor


class BackendSession:
    """Stateful bridge for disk discovery, catalog browsing and extraction."""

    def __init__(self, inventory=None, workflow=None):
        self.inventory = inventory or DiskInventory()
        self.workflow = workflow or RecoveryWorkflow()
        self.volumes = {}
        self.snapshot = None
        self.nodes = {}

    def handle(self, request, emit):
        request_id = request.get("id")
        operation = request.get("operation")
        try:
            result = self._dispatch(operation, request.get("payload") or {}, emit)
            emit({"id": request_id, "type": "result", "payload": result})
        except Exception as exc:
            emit({"id": request_id, "type": "error", "error": str(exc),
                  "errorType": type(exc).__name__})

    def _dispatch(self, operation, payload, emit):
        if operation == "list_disks":
            return [self._disk_data(disk) for disk in self.inventory.list_disks()]
        if operation == "list_partitions":
            disk_number = int(payload["diskNumber"])
            progress = self._inventory_progress(emit)
            if payload.get("deepScan"):
                volumes = self.inventory.deep_scan_ntfs_volumes(disk_number, progress)
            else:
                volumes = self.inventory.list_ntfs_volumes(disk_number, progress)
            result = []
            for volume in volumes:
                volume_id = f"{volume.disk_number}:{volume.partition_offset}"
                self.volumes[volume_id] = volume
                result.append({
                    "id": volume_id,
                    "diskNumber": volume.disk_number,
                    "partitionNumber": volume.partition_number,
                    "offset": volume.partition_offset,
                    "sizeBytes": volume.partition_size,
                    "estimatedSize": volume.partition_size_is_estimated,
                    "name": volume.display_name,
                })
            return result
        if operation == "scan_catalog":
            volume_id = str(payload["volumeId"])
            volume = self.volumes[volume_id]
            self.snapshot = self.workflow.scan_catalog(volume, self._progress(emit))
            self.nodes = {f"n{index}": node for index, node in enumerate(self.snapshot.catalog.nodes.values())}
            ids_by_identity = {id(node): node_id for node_id, node in self.nodes.items()}
            return {
                "recordCount": len(self.nodes),
                "availableExtensions": self.snapshot.catalog.available_extensions(Extractor.supported_extensions()),
                "roots": [self._node_data(node, ids_by_identity) for node in self.snapshot.catalog.root_nodes],
            }
        if operation == "catalog_children":
            node = self.nodes[str(payload["nodeId"])]
            ids_by_identity = {id(value): key for key, value in self.nodes.items()}
            return [self._node_data(child, ids_by_identity) for child in node.children]
        if operation == "extract":
            if self.snapshot is None:
                raise ValueError("Build a file catalog before starting recovery")
            selected_nodes = [self.nodes[node_id] for node_id in payload.get("selectedNodeIds", [])]
            excluded_nodes = [self.nodes[node_id] for node_id in payload.get("excludedNodeIds", [])]
            if excluded_nodes:
                catalog = self.snapshot.catalog
                eligible = catalog.eligible_files(
                    Extractor.supported_extensions(), payload.get("extensions", []),
                    int(payload.get("minimumSizeKb", 0)) * 1024,
                )
                excluded_keys = {
                    catalog.node_key(node)
                    for node in catalog.plan_selection(excluded_nodes, eligible)
                }
                selected_nodes = [
                    node for node in catalog.plan_selection(selected_nodes, eligible)
                    if catalog.node_key(node) not in excluded_keys
                ]
            summary = self.workflow.extract_selection(
                snapshot=self.snapshot,
                selected_nodes=selected_nodes,
                output_directory=payload.get("outputDirectory", ""),
                extensions=payload.get("extensions", []),
                min_file_size_kb=int(payload.get("minimumSizeKb", 0)),
                progress_callback=self._progress(emit),
            )
            return {
                "recoveredCount": summary.recovered_count,
                "candidateCount": len(summary.results),
                "reportPath": os.path.join(payload["outputDirectory"], "Recovery_Report.txt"),
            }
        raise ValueError(f"Unknown operation: {operation}")

    @staticmethod
    def _progress(emit):
        def report(event: RecoveryProgress):
            emit({"type": "progress", "payload": {
                "stage": event.stage,
                "completed": event.completed,
                "total": event.total,
                "message": event.message,
            }})
        return report

    @staticmethod
    def _inventory_progress(emit):
        def report(completed, total, message):
            emit({"type": "progress", "payload": {
                "stage": "partition-scan",
                "completed": completed,
                "total": total,
                "message": message,
            }})
        return report

    @staticmethod
    def _disk_data(disk):
        return {
            "number": disk.number,
            "model": disk.model,
            "sizeBytes": disk.size_bytes,
            "serialNumber": disk.serial_number,
            "displayName": disk.display_name,
        }

    @staticmethod
    def _node_data(node, ids_by_identity):
        return {
            "id": ids_by_identity[id(node)],
            "name": node.record.name,
            "path": node.full_path,
            "isDirectory": bool(node.record.is_dir),
            "sizeBytes": int(node.record.file_size),
            "hasChildren": bool(node.record.is_dir and node.children),
        }


def main():
    session = BackendSession()
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
            if not operation_lock.acquire(blocking=False):
                emit({"id": request.get("id"), "type": "error",
                      "error": "Another disk operation is already running", "errorType": "BusyError"})
                continue
        except (json.JSONDecodeError, AttributeError) as exc:
            emit({"id": None, "type": "error", "error": f"Invalid request: {exc}", "errorType": "ValueError"})
            continue

        def run(current_request=request):
            try:
                session.handle(current_request, emit)
            finally:
                operation_lock.release()

        threading.Thread(target=run, name="disk-recovery-request", daemon=True).start()


if __name__ == "__main__":
    main()
