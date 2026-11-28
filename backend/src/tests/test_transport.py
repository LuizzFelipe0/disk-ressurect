import io
import json
import threading
import unittest
from unittest.mock import patch

from presentation.controller import RecoveryCommandHandler
from presentation.transport import serve


class JsonLinesTransportTests(unittest.TestCase):
    def test_cancel_command_bypasses_the_busy_operation_lock(self):
        cancel_requested = threading.Event()
        scan_finished = threading.Event()
        cancellation_tokens = {}

        class Handler:
            def prepare_cancellation(self, request):
                operation_id = request["payload"]["operationId"]
                cancellation_tokens.setdefault(operation_id, threading.Event())

            def handle(self, request, emit):
                if request["operation"] == "scan_catalog":
                    prepared = request["payload"]["operationId"] in cancellation_tokens
                    self.asserted = prepared and cancel_requested.wait(timeout=2)
                    emit({"id": request["id"], "type": "result", "payload": {"cancelled": self.asserted}})
                    scan_finished.set()
                else:
                    cancellation_tokens[request["payload"]["operationId"]].set()
                    cancel_requested.set()
                    emit({"id": request["id"], "type": "result", "payload": {"accepted": True}})

        output = io.StringIO()
        requests = "\n".join((
            json.dumps({"id": "scan", "operation": "scan_catalog",
                        "payload": {"operationId": "operation-1"}}),
            json.dumps({"id": "cancel", "operation": "cancel_operation",
                        "payload": {"operationId": "operation-1"}}),
        )) + "\n"
        with patch("presentation.transport.sys.stdin", io.StringIO(requests)), \
                patch("presentation.transport.sys.stdout", output):
            serve(Handler())
            self.assertTrue(scan_finished.wait(timeout=2))
        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual({"accepted": True}, next(
            message["payload"] for message in messages if message.get("id") == "cancel"
        ))
        self.assertEqual({"cancelled": True}, next(
            message["payload"] for message in messages if message.get("id") == "scan"
        ))

    def test_prepared_scan_uses_the_same_cancellation_token_when_handle_starts(self):
        handler = object.__new__(RecoveryCommandHandler)
        handler._cancel_lock = threading.RLock()
        handler._active_cancellations = {}
        observed = []
        handler.dispatch = lambda operation, payload, _emit: {
            "prepared": handler._active_cancellations[payload["operationId"]]
            is expected_token,
        }
        request = {
            "id": "scan", "operation": "scan_catalog",
            "payload": {"operationId": "operation-2"},
        }

        handler.prepare_cancellation(request)
        expected_token = handler._active_cancellations["operation-2"]
        handler.handle(request, observed.append)

        self.assertEqual({"prepared": True}, observed[-1]["payload"])
        self.assertNotIn("operation-2", handler._active_cancellations)

    def test_malformed_prepared_scan_discards_its_cancellation_token(self):
        handler = object.__new__(RecoveryCommandHandler)
        handler._cancel_lock = threading.RLock()
        handler._active_cancellations = {}
        request = {
            "id": "", "operation": "scan_catalog",
            "payload": {"operationId": "malformed-operation"},
        }

        handler.prepare_cancellation(request)
        observed = []
        handler.handle(request, observed.append)

        self.assertEqual("error", observed[-1]["type"])
        self.assertNotIn("malformed-operation", handler._active_cancellations)

    def test_emits_ready_and_preserves_command_messages_as_json_lines(self):
        completed = threading.Event()

        class Handler:
            def handle(self, request, emit):
                emit({"id": request["id"], "type": "result", "payload": {"ok": True}})
                completed.set()

        output = io.StringIO()
        request = json.dumps({"id": "req-1", "operation": "list_disks", "payload": {}})
        with patch("presentation.transport.sys.stdin", io.StringIO(request + "\n")), \
                patch("presentation.transport.sys.stdout", output):
            serve(Handler())

        self.assertTrue(completed.wait(timeout=1))
        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(messages, [
            {"type": "ready", "payload": {"message": "Python recovery service is ready"}},
            {"id": "req-1", "type": "result", "payload": {"ok": True}},
        ])

    def test_reports_invalid_json_using_the_existing_error_shape(self):
        output = io.StringIO()
        with patch("presentation.transport.sys.stdin", io.StringIO("{invalid}\n")), \
                patch("presentation.transport.sys.stdout", output):
            serve(object())

        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(messages[0], {
            "type": "ready", "payload": {"message": "Python recovery service is ready"},
        })
        self.assertEqual(messages[1]["id"], None)
        self.assertEqual(messages[1]["type"], "error")
        self.assertTrue(messages[1]["error"].startswith("Invalid request:"))
        self.assertEqual(messages[1]["errorType"], "ValueError")


if __name__ == "__main__":
    unittest.main()
