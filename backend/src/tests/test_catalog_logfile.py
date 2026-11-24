import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.disk.entities import NTFSVolume
from modules.catalog.mapper import CatalogMapper
from modules.catalog.service import CatalogService
from ntfs.tree_builder import FileNode
from test_ntfs_logfile import _log_page


class FakeDisk:
    size = 16 * 1024

    def __init__(self):
        self.reads = []
        self.closed = False

    def read_at(self, offset, size):
        self.reads.append((offset, size))
        return bytes(size)

    def close(self):
        self.closed = True


class FakeTreeBuilder:
    nodes = {}
    root_nodes = []

    def __init__(self, *_args, **_kwargs):
        self.nodes = type(self).nodes
        self.root_nodes = type(self).root_nodes
        self.parent_reference_issue_count = 0

    def build(self, **_kwargs):
        return self.nodes

    def inject_ghosts(self, _ghosts):
        return None


class CatalogLogFileEvidenceTests(unittest.TestCase):
    def test_catalog_summary_flows_through_dto_without_creating_recovery_items(self):
        data = _log_page(b"RSTR") + _log_page(b"RCRD")
        record = SimpleNamespace(
            name="$LogFile",
            file_size=len(data),
            resident_data=data,
            data_runs=(),
            data_is_complete=True,
            is_dir=False,
            is_allocated=True,
            raw_data=b"logfile-record",
            is_valid=True,
            index=2,
            mft_offset=2048,
            named_data_streams={},
            is_metadata_consistent=True,
        )
        logfile = FileNode(record)
        disk = FakeDisk()
        volume = NTFSVolume(0, 1, 0, disk.size, 512, 4, 1024, 0, 0, ())
        FakeTreeBuilder.nodes = {record.index: logfile}
        FakeTreeBuilder.root_nodes = [logfile]

        with patch("modules.catalog.service.TreeBuilder", FakeTreeBuilder):
            with patch("modules.recovery.extractor.Extractor.supported_extensions", return_value=(".jpg",)):
                snapshot = CatalogService(lambda _number: disk).build(
                    volume,
                    include_orphaned=True,
                    precomputed_orphans={},
                )

        summary = snapshot.ntfs_log_file_summary
        self.assertEqual(1, len(snapshot.catalog.nodes))
        self.assertEqual(2, summary["pagesExamined"])
        self.assertEqual(1, summary["restartPages"])
        self.assertEqual(1, summary["recordPages"])
        self.assertEqual(["0x0000000000010008"], summary["currentLsns"])
        self.assertEqual("structural_evidence_only", summary["recoveryClaim"])
        self.assertEqual([], disk.reads)
        self.assertTrue(disk.closed)

        dto = CatalogMapper.catalog(
            snapshot,
            {id(node): f"n{index}" for index, node in enumerate(snapshot.catalog.nodes.values())},
        ).to_dict()
        self.assertEqual(summary, dto["ntfsLogFileEvidence"])
        self.assertNotIn("events", dto["ntfsLogFileEvidence"])
        self.assertNotIn("recoveredFiles", dto["ntfsLogFileEvidence"])


if __name__ == "__main__":
    unittest.main()
