import io
import json
import threading
import unittest
from unittest.mock import patch

from presentation.transport import serve


class JsonLinesTransportTests(unittest.TestCase):
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
