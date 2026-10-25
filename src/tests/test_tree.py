import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ntfs.tree_builder import FileNode, TreeBuilder


class TreeBuilderTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
