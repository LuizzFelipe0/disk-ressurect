import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from infrastructure.filesystems.ntfs.discovery.tree_builder import FileNode, TreeBuilder


class TreeBuilderTests(unittest.TestCase):
    def test_release_source_tree_breaks_mft_references_after_catalog_adaptation(self):
        root = FileNode(SimpleNamespace(index=5, name="root", is_allocated=True, is_dir=True))
        child = FileNode(SimpleNamespace(index=42, name="photo.jpg", is_allocated=False, is_dir=False))
        root.children.append(child)
        child.parent = root
        builder = TreeBuilder(disk=None, fragments=[], base_offset=0)
        builder.nodes = {5: root, 42: child}
        builder.mft_records = {42: child.record}
        builder.root_nodes = [root]

        builder.release_source_tree()

        self.assertEqual({}, builder.nodes)
        self.assertEqual({}, builder.mft_records)
        self.assertEqual([], builder.root_nodes)
        self.assertIsNone(child.parent)
        self.assertEqual([], root.children)

    def test_parent_sequence_mismatch_keeps_a_stale_reference_unlinked(self):
        parent = FileNode(SimpleNamespace(
            index=5, sequence_number=8, name="root", is_allocated=True, is_dir=True,
        ))
        child_record = SimpleNamespace(
            index=42, sequence_number=1, parent_index=5, parent_sequence_number=7,
            name="old.jpg", is_allocated=False, is_dir=False,
            metadata_warnings=[], is_metadata_consistent=True,
        )
        child = FileNode(child_record)
        builder = TreeBuilder(disk=None, fragments=[], base_offset=0)
        builder.nodes = {5: parent, 42: child}

        builder._link_nodes()

        self.assertIsNone(child.parent)
        self.assertNotIn(child, parent.children)
        self.assertFalse(child_record.is_metadata_consistent)
        self.assertIn(
            "parent_sequence_number_does_not_match_parent_record",
            child_record.metadata_warnings,
        )

    def test_parent_reference_to_a_file_is_reported_as_inconsistent(self):
        parent = FileNode(SimpleNamespace(
            index=5, sequence_number=8, name="document.pdf", is_allocated=True, is_dir=False,
        ))
        child_record = SimpleNamespace(
            index=42, sequence_number=1, parent_index=5, parent_sequence_number=8,
            name="child.jpg", is_allocated=False, is_dir=False,
            metadata_warnings=[], is_metadata_consistent=True,
        )
        child = FileNode(child_record)
        builder = TreeBuilder(disk=None, fragments=[], base_offset=0)
        builder.nodes = {5: parent, 42: child}

        builder._link_nodes()

        self.assertIsNone(child.parent)
        self.assertFalse(child_record.is_metadata_consistent)
        self.assertIn("parent_reference_targets_non_directory", child_record.metadata_warnings)

    def test_resolves_paths_and_marks_deleted_files(self):
        root_record = SimpleNamespace(
            index=5,
            name="root",
            is_allocated=True,
            is_dir=True,
        )
        child_record = SimpleNamespace(
            index=42,
            name="report:final.pdf",
            is_allocated=False,
            is_dir=False,
        )
        root = FileNode(root_record)
        child = FileNode(child_record)
        root.children.append(child)
        child.parent = root

        builder = TreeBuilder(disk=None, fragments=[], base_offset=0)
        builder.root_nodes = [root]
        builder._resolve_paths()

        expected_path = os.path.join("root", "[DELETED]_report_final.pdf")
        self.assertEqual(child.full_path, expected_path)
        self.assertIs(child.parent, root)

    def test_path_resolution_handles_deep_trees_without_python_recursion(self):
        root_record = SimpleNamespace(index=5, name="root", is_allocated=True, is_dir=True)
        root = FileNode(root_record)
        current = root
        for index in range(1, 1_200):
            child = FileNode(SimpleNamespace(index=index, name=f"folder-{index}",
                is_allocated=True, is_dir=True))
            current.children.append(child)
            child.parent = current
            current = child

        builder = TreeBuilder(disk=None, fragments=[], base_offset=0)
        builder.root_nodes = [root]
        builder._resolve_paths()

        self.assertTrue(current.full_path.endswith(os.path.join("folder-1199")))

    def test_breaks_corrupt_parent_cycles_and_keeps_records_reachable(self):
        first = FileNode(SimpleNamespace(index=10, name="first", is_allocated=True, is_dir=True))
        second = FileNode(SimpleNamespace(index=11, name="second", is_allocated=True, is_dir=True))
        first.parent = second
        first.children.append(second)
        second.parent = first
        second.children.append(first)
        builder = TreeBuilder(disk=None, fragments=[], base_offset=0)
        builder.nodes = {10: first, 11: second}

        builder._detach_parent_cycles()
        builder.root_nodes = [node for node in builder.nodes.values() if node.parent is None]
        builder._resolve_paths()

        self.assertEqual(len(builder.root_nodes), 1)
        self.assertIs(builder.root_nodes[0], first)
        self.assertTrue(first.full_path)
        self.assertTrue(second.full_path)

    def test_reports_progress_while_checking_a_large_parent_chain(self):
        nodes = {}
        for index in range(9000):
            node = FileNode(SimpleNamespace(index=index, name=f"node-{index}",
                is_allocated=True, is_dir=True))
            nodes[index] = node
        for index in range(8999):
            node = nodes[index]
            node.parent = nodes[index + 1]
            nodes[index + 1].children.append(node)

        events = []
        builder = TreeBuilder(disk=None, fragments=[], base_offset=0)
        builder.nodes = nodes
        builder._detach_parent_cycles(
            lambda phase, completed, total: events.append((phase, completed, total)),
        )

        self.assertTrue(any(phase == "hierarchy" and completed == 4096
            for phase, completed, _total in events))
        self.assertEqual(events[-1], ("hierarchy", 9000, 9000))


if __name__ == "__main__":
    unittest.main()
