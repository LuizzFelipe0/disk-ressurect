import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.commands.controller import RecoveryCommandHandler
from modules.commands.dto import CommandRequestDto, ProgressEventDto
from modules.disk_discovery.dto import PartitionScanRequestDto
from modules.disk_discovery.service import DiskDiscoveryService
from modules.recovery.dto import RecoveryRequestDto


class EmptyInventory:
    def list_disks(self):
        return []


class EmptyRepository:
    def load(self, _disk):
        return None


class EmptyWorkflow:
    pass


class EmptyCatalogService:
    pass


def make_handler():
    discovery = DiskDiscoveryService(EmptyInventory(), EmptyRepository())
    return RecoveryCommandHandler(discovery, EmptyCatalogService(), EmptyWorkflow())


class CommandContractTests(unittest.TestCase):
    def test_command_request_rejects_missing_identity_and_payload_with_wrong_shape(self):
        with self.assertRaisesRegex(ValueError, "Request id"):
            CommandRequestDto.from_message({"operation": "list_disks"})
        with self.assertRaisesRegex(ValueError, "payload must be a JSON object"):
            CommandRequestDto.from_message({"id": "req-1", "operation": "list_disks", "payload": []})

    def test_partition_scan_request_validates_disk_number_and_deep_scan_flag(self):
        self.assertEqual(PartitionScanRequestDto.from_payload({"diskNumber": "3", "deepScan": True}).disk_number, 3)
        resume = PartitionScanRequestDto.from_payload({"diskNumber": 3, "deepScan": True, "resume": True})
        self.assertTrue(resume.resume)
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            PartitionScanRequestDto.from_payload({"diskNumber": -1})
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            PartitionScanRequestDto.from_payload({"diskNumber": 1, "deepScan": "true"})
        with self.assertRaisesRegex(ValueError, "resume requires deepScan"):
            PartitionScanRequestDto.from_payload({"diskNumber": 1, "resume": True})

    def test_recovery_request_rejects_invalid_filters_and_ids(self):
        with self.assertRaisesRegex(ValueError, "selectedNodeIds"):
            RecoveryRequestDto.from_payload({"selectedNodeIds": [1]})
        with self.assertRaisesRegex(ValueError, "minimumSizeKb"):
            RecoveryRequestDto.from_payload({"minimumSizeKb": -1})

    def test_command_handler_maps_errors_to_stable_message_contract(self):
        handler = make_handler()
        messages = []

        handler.handle({"id": "req-2", "operation": "not_a_command", "payload": {}}, messages.append)

        self.assertEqual(messages, [{
            "id": "req-2",
            "type": "error",
            "error": "Unknown operation: not_a_command",
            "errorType": "ValueError",
        }])

    def test_progress_event_dto_preserves_desktop_contract(self):
        event = ProgressEventDto("extract", 2, 5, "Recovered file").to_dict()

        self.assertEqual(event["type"], "progress")
        self.assertEqual(event["payload"], {
            "stage": "extract", "completed": 2, "total": 5, "message": "Recovered file",
        })


if __name__ == "__main__":
    unittest.main()
