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


if __name__ == "__main__":
    unittest.main()
