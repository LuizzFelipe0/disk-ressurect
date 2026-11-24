import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from presentation.controller import RecoveryCommandHandler
from presentation.transport import CommandRequestDto, ProgressEventDto
from modules.catalog.dto import CarvingOptionsDto, VolumeSelectionRequestDto
from modules.deep_scan.dto import PartitionScanRequestDto
from modules.disk.service import DiskService
from modules.deep_scan.service import DeepScanService
from modules.validation.service import ValidationService
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
    inventory, repository = EmptyInventory(), EmptyRepository()
    disk_service = DiskService(inventory, repository)
    return RecoveryCommandHandler(
        disk_service, DeepScanService(inventory, disk_service, repository, repository),
        ValidationService(inventory, disk_service, repository),
        EmptyCatalogService(), EmptyCatalogService(), EmptyWorkflow(),
    )


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

    def test_catalog_request_defaults_to_maximum_recovery_and_validates_flags(self):
        default_request = VolumeSelectionRequestDto.from_payload({"volumeId": "0:4096"})
        self.assertTrue(default_request.include_orphaned)
        self.assertEqual(default_request.carving_options, CarvingOptionsDto(64, 16384, 512, 1024))
        self.assertTrue(default_request.force_fresh_validation)
        self.assertFalse(VolumeSelectionRequestDto.from_payload({
            "volumeId": "0:4096", "includeOrphaned": False,
        }).include_orphaned)
        self.assertFalse(VolumeSelectionRequestDto.from_payload({
            "volumeId": "0:4096", "forceFreshValidation": False,
        }).force_fresh_validation)
        self.assertTrue(VolumeSelectionRequestDto.from_payload({
            "volumeId": "0:4096", "includeOrphaned": True,
        }).include_orphaned)
        self.assertTrue(VolumeSelectionRequestDto.from_payload({
            "volumeId": "0:4096", "forceFreshValidation": True,
        }).force_fresh_validation)
        with self.assertRaisesRegex(ValueError, "includeOrphaned must be a boolean"):
            VolumeSelectionRequestDto.from_payload({"volumeId": "0:4096", "includeOrphaned": "yes"})
        with self.assertRaisesRegex(ValueError, "forceFreshValidation must be a boolean"):
            VolumeSelectionRequestDto.from_payload({"volumeId": "0:4096", "forceFreshValidation": "yes"})

    def test_catalog_request_validates_bounded_carving_options(self):
        request = VolumeSelectionRequestDto.from_payload({
            "volumeId": "0:4096", "includeOrphaned": True,
            "carvingOptions": {
                "scanBudgetGiB": 16, "maxFiles": 16384, "maxRetainedMiB": 256,
                "maxCandidateReadMiBPerFormat": 1024,
            },
        })
        self.assertEqual(request.carving_options, CarvingOptionsDto(16, 16384, 256, 1024))
        for invalid in (
            {"scanBudgetGiB": 0},
            {"scanBudgetGiB": 128},
            {"scanBudgetGiB": True},
            {"maxFiles": 32768},
            {"maxFiles": "512"},
            {"maxRetainedMiB": 1024},
            {"maxCandidateReadMiBPerFormat": 2048},
            {"maxCandidateReadMiBPerFormat": True},
            {"unknown": 1},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                VolumeSelectionRequestDto.from_payload({
                    "volumeId": "0:4096", "carvingOptions": invalid,
                })

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
