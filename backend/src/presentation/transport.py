from dataclasses import dataclass
import json
import sys
import threading
from typing import Any


@dataclass(frozen=True)
class CommandRequestDto:
    request_id: str
    operation: str
    payload: dict[str, Any]

    @classmethod
    def from_message(cls, message):
        if not isinstance(message, dict):
            raise ValueError("Request must be a JSON object")
        request_id, operation = message.get("id"), message.get("operation")
        payload = message.get("payload", {})
        if payload is None:
            payload = {}
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("Request id must be a non-empty string")
        if not isinstance(operation, str) or not operation:
            raise ValueError("Request operation must be a non-empty string")
        if not isinstance(payload, dict):
            raise ValueError("Request payload must be a JSON object")
        return cls(request_id, operation, payload)


@dataclass(frozen=True)
class CommandResultDto:
    request_id: str
    payload: Any

    def to_dict(self):
        payload = self.payload.to_dict() if hasattr(self.payload, "to_dict") else self.payload
        return {"id": self.request_id, "type": "result", "payload": payload}


@dataclass(frozen=True)
class CommandErrorDto:
    request_id: str | None
    error: str
    error_type: str

    def to_dict(self):
        return {"id": self.request_id, "type": "error", "error": self.error, "errorType": self.error_type}


@dataclass(frozen=True)
class ProgressEventDto:
    stage: str
    completed: int
    total: int
    message: str

    def to_dict(self):
        return {
            "type": "progress",
            "payload": {
                "stage": self.stage,
                "completed": self.completed,
                "total": self.total,
                "message": self.message,
            },
        }


def serve(handler):
    """Adapt stdin/stdout JSON Lines to the command controller."""
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
