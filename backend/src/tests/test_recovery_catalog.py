import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from domain.recovery_catalog import RecoveryCatalog


def make_node(index, name, size, is_dir=False, path=None):
    record = SimpleNamespace(
        index=index,
        sequence_number=1,
        name=name,
        file_size=size,
        is_dir=is_dir,
    )
    return SimpleNamespace(
        record=record,
        full_path=path or name,
        parent=None,
        children=[],
    )


class RecoveryCatalogTests(unittest.TestCase):
    def setUp(self):
        self.root = make_node(5, "root", 0, is_dir=True)
        self.folder = make_node(20, "selected folder", 0, is_dir=True, path="root/selected folder")
        self.photo = make_node(21, "photo.JPG", 4096, path="root/selected folder/photo.JPG")
        self.document = make_node(22, "report.pdf", 2048, path="root/selected folder/report.pdf")
        self.tiny_photo = make_node(23, "tiny.jpg", 30, path="root/selected folder/tiny.jpg")
        self.folder.parent = self.root
        self.root.children.append(self.folder)
        for node in (self.photo, self.document, self.tiny_photo):
            node.parent = self.folder
            self.folder.children.append(node)
        self.catalog = RecoveryCatalog(
            {node.record.index: node for node in (self.root, self.folder, self.photo, self.document, self.tiny_photo)},
            [self.root],
        )

    def test_lists_only_extensions_supported_by_the_recovery_engine(self):
        self.assertEqual(self.catalog.available_extensions({".jpg", ".pdf", ".mp4"}), [".jpg", ".pdf"])

    def test_file_type_and_minimum_size_filters_are_case_insensitive(self):
        candidates = self.catalog.eligible_files({".jpg", ".pdf"}, {".JPG"}, min_file_size=100)
        self.assertEqual(candidates, [self.photo])

    def test_folder_selection_expands_to_filtered_descendants_once(self):
        eligible = self.catalog.eligible_files({".jpg", ".pdf"}, {".jpg", ".pdf"}, min_file_size=100)
        selected = self.catalog.plan_selection([self.root, self.folder, self.photo], eligible)
        self.assertEqual(selected, [self.photo, self.document])

    def test_explicitly_empty_extension_selection_recovers_no_files(self):
        self.assertEqual(self.catalog.eligible_files({".jpg", ".pdf"}, extensions=set()), [])

    def test_catalog_plan_expands_deep_folder_trees_iteratively(self):
        root = make_node(100, "root", 0, is_dir=True)
        parent = root
        nodes = [root]
        for index in range(101, 1_301):
            child = make_node(index, f"folder-{index}", 0, is_dir=True)
            child.parent = parent
            parent.children.append(child)
            parent = child
            nodes.append(child)
        photo = make_node(1_301, "deep.jpg", 20, path=f"{parent.full_path}/deep.jpg")
        photo.parent = parent
        parent.children.append(photo)
        nodes.append(photo)
        catalog = RecoveryCatalog({node.record.index: node for node in nodes}, [root])

        selected = catalog.plan_selection([root], catalog.eligible_files({".jpg"}))

        self.assertEqual(selected, [photo])


if __name__ == "__main__":
    unittest.main()
