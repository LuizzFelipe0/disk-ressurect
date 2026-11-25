import os
import struct
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.disk.entities import NTFSVolume
from modules.catalog.mapper import CatalogMapper
from infrastructure.filesystems.ntfs.catalog_builder import CatalogBuilder
from infrastructure.filesystems.ntfs.readers.file_content_reader import NTFSFileContentReader
from infrastructure.filesystems.ntfs.mft.parser import NTFSDataStream
from infrastructure.filesystems.ntfs.discovery.tree_builder import FileNode


def _index_file(path, original_size):
    encoded = path.encode("utf-16le")
    return struct.pack("<Q Q Q I", 2, original_size, 134_000_000_000_000_000, len(path)) + encoded


def _usn_record(name="deleted.jpg", reason=0x200):
    encoded = name.encode("utf-16le")
    length = (60 + len(encoded) + 7) & ~7
    data = bytearray(length)
    struct.pack_into("<IHH", data, 0, length, 2, 0)
    struct.pack_into("<Q Q q q I I I I H H", data, 8,
                     (4 << 48) | 11, (3 << 48) | 5, 9, 0,
                     reason, 0, 0, 0, len(encoded), 60)
    data[60:60 + len(encoded)] = encoded
    return bytes(data)


class FakeDisk:
    def __init__(self, _number):
        self.size = 32 * 1024
        self.closed = False
        self.reads = []

    def read_at(self, offset, size):
        self.reads.append((offset, size))
        return bytes(size)

    def close(self):
        self.closed = True


class FakeTreeBuilder:
    nodes = {}
    root_nodes = []
    parent_reference_issue_count = 0

    def __init__(self, *_args, **_kwargs):
        self.nodes = type(self).nodes
        self.root_nodes = type(self).root_nodes

    def build(self, **_kwargs):
        return self.nodes

    def inject_ghosts(self, _ghosts):
        return None


def _record(name, size, *, is_dir=False, content=None, index=1, streams=None):
    if content is None:
        content = b""
    return SimpleNamespace(
        name=name,
        file_size=size,
        is_dir=is_dir,
        is_allocated=True,
        data_is_complete=True,
        resident_data=content,
        data_runs=(),
        raw_data=b"record",
        is_valid=True,
        index=index,
        mft_offset=index * 1024,
        named_data_streams=streams or {},
        is_metadata_consistent=True,
    )


def _catalog_nodes(*, original_size=12, content_size=None, extension="jpg", journal=None,
                   journal_stream_size=None, journal_stream_complete=True,
                   include_journal=True):
    root = FileNode(_record("$Recycle.Bin", 0, is_dir=True, index=10))
    sid = FileNode(_record("S-1-5-21", 0, is_dir=True, index=11))
    sid.parent = root
    root.children.append(sid)
    index_data = _index_file(r"C:\Users\Ada\Photos\..\lost." + extension, original_size)
    index_node = FileNode(_record(
        f"$Iabc.{extension}", len(index_data), content=index_data, index=12,
    ))
    content_size = original_size if content_size is None else content_size
    content_node = FileNode(_record(
        f"$Rabc.{extension}", content_size, content=b"X" * content_size, index=13,
    ))
    index_node.parent = sid
    content_node.parent = sid
    sid.children.extend((index_node, content_node))
    nodes = {10: root, 11: sid, 12: index_node, 13: content_node}
    roots = [root]
    if include_journal:
        journal = journal if journal is not None else _usn_record()
        declared_size = journal_stream_size if journal_stream_size is not None else len(journal)
        stream = NTFSDataStream(
            name="$J", file_size=declared_size, allocated_size=declared_size,
            resident_data=journal, data_runs=(), is_resident=True,
            is_complete=journal_stream_complete,
        )
        extend = FileNode(_record("$Extend", 0, is_dir=True, index=15))
        journal_node = FileNode(_record(
            "$UsnJrnl", 0, index=14, streams={"$j": stream},
        ))
        journal_node.parent = extend
        extend.children.append(journal_node)
        nodes[14] = journal_node
        nodes[15] = extend
        roots.append(extend)
    return nodes, roots, index_node, content_node


class CatalogArtifactSourceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.volume = NTFSVolume(3, 1, 0, 8192, 512, 4, 1024, 0, 0, ())

    def _build(self, *, nodes, roots, disk=None, reader_factory=None):
        disk = disk or FakeDisk(3)
        FakeTreeBuilder.nodes = nodes
        FakeTreeBuilder.root_nodes = roots
        patches = [
            patch("infrastructure.filesystems.ntfs.catalog_builder.TreeBuilder", FakeTreeBuilder),
            patch("infrastructure.filesystems.ntfs.catalog_builder.GhostMFTCarver"),
            patch("infrastructure.recovery.extractor.Extractor.supported_extensions",
                  return_value=(".jpg",)),
        ]
        if reader_factory is not None:
            patches.append(patch("infrastructure.filesystems.ntfs.catalog_builder.NTFSFileContentReader", reader_factory))
        for active in patches:
            active.start()
            self.addCleanup(active.stop)
        snapshot = CatalogBuilder(lambda _number: disk).build(
            self.volume,
            include_orphaned=True,
            precomputed_orphans={},
        )
        return snapshot, disk

    def test_adds_safe_recycle_bin_alias_with_metadata_only(self):
        nodes, roots, _index, content = _catalog_nodes(original_size=12)
        original_record = content.record

        snapshot, _disk = self._build(nodes=nodes, roots=roots)
        alias = next(node for node in snapshot.catalog.nodes.values()
                     if node.properties.get("recoverySource") == "recycle_bin")
        ids = {id(node): f"node-{index}" for index, node in enumerate(snapshot.catalog.nodes.values())}
        dto = CatalogMapper.catalog(snapshot, ids).to_dict()
        alias_dto = next(node for node in dto["roots"]
                         if node.get("recoverySource") == "recycle_bin")

        self.assertNotEqual(
            dict(alias.candidate.evidence[0].details).get("recordNumber"), original_record.index,
        )
        self.assertEqual(alias.properties["recoverySource"], "recycle_bin")
        self.assertEqual("$Rabc.jpg", original_record.name)
        self.assertEqual("Lost_Files_DeepScan/RecycleBin/" + alias.name,
                         alias.full_path.replace("\\", "/"))
        self.assertNotIn("..", alias.full_path)
        self.assertEqual(r"C:\Users\Ada\Photos\..\lost.jpg", alias_dto["originalPath"])
        self.assertEqual(12, alias_dto["originalSizeBytes"])
        self.assertTrue(alias_dto["deletionTimestampUtc"].endswith("+00:00"))
        self.assertNotIn("content", alias_dto)
        self.assertEqual(1, snapshot.recycle_bin_summary["aliasesAdded"])
        self.assertEqual("complete", snapshot.usn_journal_summary["status"])
        self.assertEqual(1, snapshot.usn_journal_summary["deletedEvents"])
        self.assertNotIn("events", snapshot.usn_journal_summary)

    def test_size_mismatch_and_unsupported_extension_do_not_create_aliases(self):
        mismatch_nodes, mismatch_roots, _index, _content = _catalog_nodes(
            original_size=12, content_size=9,
        )
        mismatch_snapshot, _ = self._build(nodes=mismatch_nodes, roots=mismatch_roots)
        self.assertEqual(0, mismatch_snapshot.recycle_bin_summary["aliasesAdded"])
        self.assertEqual(1, mismatch_snapshot.recycle_bin_summary["metadataMismatchCount"])
        self.assertEqual("inconclusive", mismatch_snapshot.recycle_bin_summary["status"])

        unsupported_nodes, unsupported_roots, _index, _content = _catalog_nodes(
            original_size=12, extension="txt",
        )
        unsupported_snapshot, _ = self._build(nodes=unsupported_nodes, roots=unsupported_roots)
        self.assertEqual(0, unsupported_snapshot.recycle_bin_summary["aliasesAdded"])
        self.assertEqual(1, unsupported_snapshot.recycle_bin_summary["unsupportedExtensionCount"])

    def test_usn_reader_is_bounded_and_summary_marks_partial_without_events(self):
        journal = _usn_record("deleted.jpg")
        nodes, roots, _index, _content = _catalog_nodes(
            original_size=12, journal=journal,
            journal_stream_size=64 * 1024 * 1024 + 1,
        )
        calls = []

        class BoundedReader:
            def iter_chunks(self, _node):
                return iter(())

            def read_named_stream(self, _node, name, max_bytes):
                calls.append((name, max_bytes))
                return journal

        snapshot, _ = self._build(
            nodes=nodes, roots=roots,
            reader_factory=lambda *_args, **_kwargs: BoundedReader(),
        )

        self.assertEqual([("$J", 64 * 1024 * 1024)], calls)
        self.assertEqual("inconclusive", snapshot.usn_journal_summary["status"])
        self.assertTrue(snapshot.usn_journal_summary["limitReached"])
        self.assertEqual(1, snapshot.usn_journal_summary["deletedEvents"])
        self.assertNotIn("events", snapshot.usn_journal_summary)

    def test_usn_deletion_matches_exact_mft_generation_and_adds_validated_alias(self):
        nodes, roots, _index, _content = _catalog_nodes(
            original_size=12, extension="txt",
        )
        deleted_data = b"\xff\xd8\xff\xe0\x00\x04\x00\x00"
        deleted_record = _record(
            "damaged-name.tmp", len(deleted_data), content=deleted_data, index=11,
        )
        deleted_record.sequence_number = 4
        deleted_record.is_allocated = False
        deleted_record.is_valid = True
        deleted_node = FileNode(deleted_record)
        nodes[11] = deleted_node
        roots.append(deleted_node)

        snapshot, _ = self._build(nodes=nodes, roots=roots)

        aliases = [node for node in snapshot.catalog.nodes.values()
                   if node.properties.get("recoverySource") == "usn_journal_mft"]
        self.assertEqual(len(aliases), 1)
        self.assertEqual(aliases[0].name, "deleted.jpg")
        self.assertEqual("Lost_Files_DeepScan/USNJournal/deleted.jpg",
                         aliases[0].full_path.replace("\\", "/"))
        self.assertEqual("damaged-name.tmp", deleted_record.name)
        self.assertEqual(1, snapshot.usn_journal_summary["matchedDeletedMftRecords"])
        self.assertEqual(1, snapshot.usn_journal_summary["signatureMatchedRecords"])
        self.assertEqual(1, snapshot.usn_journal_summary["aliasesAdded"])

    def test_usn_reference_to_reused_mft_slot_does_not_create_alias(self):
        nodes, roots, _index, _content = _catalog_nodes(
            original_size=12, extension="txt",
        )
        reused_record = _record(
            "current.jpg", 8, content=b"\xff\xd8\xff\xe0\x00\x04\x00\x00", index=11,
        )
        reused_record.sequence_number = 99
        reused_record.is_valid = True
        reused_record.is_metadata_consistent = True
        nodes[11] = FileNode(reused_record)
        roots.append(nodes[11])

        snapshot, _ = self._build(nodes=nodes, roots=roots)

        self.assertEqual(1, snapshot.usn_journal_summary["staleReferences"])
        self.assertEqual(0, snapshot.usn_journal_summary["aliasesAdded"])

    def test_incomplete_usn_stream_does_not_break_catalog(self):
        nodes, roots, _index, _content = _catalog_nodes(journal_stream_complete=False)
        snapshot, _ = self._build(nodes=nodes, roots=roots)

        self.assertEqual("inconclusive", snapshot.usn_journal_summary["status"])
        self.assertEqual(0, snapshot.usn_journal_summary["bytesRead"])
        self.assertEqual(0, snapshot.usn_journal_summary["parsedRecords"])
        self.assertEqual(7, len(snapshot.catalog.nodes))

    def test_recycle_bin_looking_siblings_outside_the_bin_are_not_aliased(self):
        nodes, roots, _index, _content = _catalog_nodes(include_journal=False)
        unrelated = FileNode(_record("Downloads", 0, is_dir=True, index=30))
        index_data = _index_file(r"C:\Users\Ada\Downloads\report.jpg", 12)
        index_node = FileNode(_record("$Ifake", len(index_data), content=index_data, index=31))
        content_node = FileNode(_record("$Rfake", 12, content=b"X" * 12, index=32))
        index_node.parent = unrelated
        content_node.parent = unrelated
        unrelated.children.extend((index_node, content_node))
        nodes.update({30: unrelated, 31: index_node, 32: content_node})
        roots.append(unrelated)

        snapshot, _ = self._build(nodes=nodes, roots=roots)

        self.assertEqual(1, snapshot.recycle_bin_summary["aliasesAdded"])
        self.assertEqual(1, snapshot.recycle_bin_summary["indexCount"])


if __name__ == "__main__":
    unittest.main()
