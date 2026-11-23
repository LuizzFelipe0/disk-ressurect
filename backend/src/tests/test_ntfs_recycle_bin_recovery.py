import struct
import unittest
from types import SimpleNamespace

from ntfs.artifact_sources import RecycleBinRecoveryHelper


def _index_data(path, original_size):
    encoded_path = path.encode("utf-16le")
    return (
        struct.pack("<Q Q Q", 2, original_size, 134_000_000_000_000_000)
        + struct.pack("<I", len(path))
        + encoded_path
    )


def _node(name, size, parent, *, index=1, is_dir=False, mft_offset=0):
    record = SimpleNamespace(
        name=name,
        file_size=size,
        is_dir=is_dir,
        index=index,
        mft_offset=mft_offset,
        parent_index=getattr(getattr(parent, "record", None), "index", 5),
        parent_sequence_number=1,
    )
    return SimpleNamespace(record=record, parent=parent, children=[])


class RecycleBinRecoveryHelperTests(unittest.TestCase):
    def test_pairs_token_only_with_sibling_in_same_directory(self):
        directory_a = _node("SID-A", 0, None, index=20, is_dir=True)
        directory_b = _node("SID-B", 0, None, index=21, is_dir=True)
        index_data = _index_data(r"C:\Users\Ada\..\..\Pictures\lost.jpg", 123)
        index_node = _node("$Iabc123.jpg", len(index_data), directory_a, index=22, mft_offset=8192)
        content_a = _node("$Rabc123.jpg", 123, directory_a, index=23)
        content_b = _node("$Rabc123.jpg", 123, directory_b, index=24)
        callback_calls = []

        def read_index(node, limit):
            callback_calls.append((node, limit))
            return index_data

        results = RecycleBinRecoveryHelper().associate(
            [directory_a, directory_b, index_node, content_a, content_b], read_index,
        )

        self.assertEqual(1, len(results))
        association = results[0]
        self.assertEqual("paired", association.status)
        self.assertIs(content_a, association.content_node)
        self.assertEqual(r"C:\Users\Ada\..\..\Pictures\lost.jpg", association.metadata.original_path)
        self.assertEqual(123, association.metadata.size_bytes)
        self.assertIsNotNone(association.metadata.timestamp_utc)
        self.assertEqual(8192, association.metadata.source_offset)
        self.assertEqual(1, len(callback_calls))
        self.assertEqual(128 * 1024, callback_calls[0][1])
        self.assertNotIn("..", association.target_name)
        self.assertNotIn("\\", association.target_name)
        self.assertNotIn("/", association.target_name)
        self.assertTrue(association.target_name.endswith("lost.jpg"))

    def test_same_token_in_another_directory_is_not_a_pair(self):
        directory_a = _node("A", 0, None, index=30, is_dir=True)
        directory_b = _node("B", 0, None, index=31, is_dir=True)
        index_data = _index_data(r"E:\old.txt", 9)
        index_node = _node("$Iabc.txt", len(index_data), directory_a, index=32)
        content_node = _node("$Rabc.txt", 9, directory_b, index=33)

        results = RecycleBinRecoveryHelper().associate(
            [directory_a, directory_b, index_node, content_node],
            lambda _node, _limit: index_data,
        )

        self.assertEqual("missing_content", results[0].status)
        self.assertIsNone(results[0].content_node)

    def test_reports_ambiguous_content_siblings(self):
        directory = _node("SID", 0, None, index=40, is_dir=True)
        index_data = _index_data(r"E:\old.txt", 9)
        index_node = _node("$Iabc.txt", len(index_data), directory, index=41)
        content_a = _node("$Rabc.txt", 9, directory, index=42)
        content_b = _node("$Rabc.txt", 9, directory, index=43)

        result = RecycleBinRecoveryHelper().associate(
            [directory, index_node, content_a, content_b],
            lambda _node, _limit: index_data,
        )[0]

        self.assertEqual("ambiguous", result.status)
        self.assertEqual("multiple_content_siblings", result.reason)

    def test_reports_original_content_size_mismatch(self):
        directory = _node("SID", 0, None, index=50, is_dir=True)
        index_data = _index_data(r"E:\old.txt", 10)
        index_node = _node("$Iabc.txt", len(index_data), directory, index=51)
        content_node = _node("$Rabc.txt", 9, directory, index=52)

        result = RecycleBinRecoveryHelper().associate(
            [directory, index_node, content_node],
            lambda _node, _limit: index_data,
        )[0]

        self.assertEqual("metadata_mismatch", result.status)
        self.assertEqual("original_and_content_sizes_differ", result.reason)
        self.assertIs(content_node, result.content_node)
        self.assertIsNotNone(result.metadata)

    def test_rejects_oversized_or_incomplete_index_before_pairing(self):
        directory = _node("SID", 0, None, index=60, is_dir=True)
        oversize = _node("$Ilarge.txt", 1024, directory, index=61)
        invalid_data = _node("$Ibad.txt", 24, directory, index=62)
        callback_calls = []

        def read_index(node, limit):
            callback_calls.append((node, limit))
            return b"bad data" * 2

        results = RecycleBinRecoveryHelper(max_index_bytes=64).associate(
            [directory, oversize, invalid_data], read_index,
        )

        self.assertEqual(["limited", "incomplete"], [item.status for item in results])
        self.assertEqual(["index_exceeds_read_limit", "index_read_size_mismatch"],
                         [item.reason for item in results])
        self.assertEqual([invalid_data], [call[0] for call in callback_calls])
        self.assertTrue(all(call[1] == 64 for call in callback_calls))

    def test_rejects_metadata_with_invalid_path_bytes(self):
        directory = _node("SID", 0, None, index=70, is_dir=True)
        malformed = struct.pack("<Q Q Q I", 2, 1, 0, 2) + b"\x00\xd8\x00\xd8"
        index_node = _node("$Ibad.txt", len(malformed), directory, index=71)

        result = RecycleBinRecoveryHelper().associate(
            [directory, index_node], lambda _node, _limit: malformed,
        )[0]

        self.assertEqual("invalid_index", result.status)
        self.assertEqual("index_format_invalid", result.reason)


if __name__ == "__main__":
    unittest.main()
