import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.catalog.mapper import CatalogMapper
from modules.catalog.models import RecoveryCatalogSnapshot
from modules.catalog.service import CatalogService
from domain.recovery_catalog import RecoveryCatalog


class CatalogSearchTests(unittest.TestCase):
    def setUp(self):
        self.root = SimpleNamespace(
            record=SimpleNamespace(name="Photos", file_size=0, is_dir=True),
            full_path="Users/Photos", children=[], parent=None,
        )
        self.photo = SimpleNamespace(
            record=SimpleNamespace(name="Summer.JPG", file_size=128, is_dir=False),
            full_path="Users/Photos/Summer.JPG", children=[], parent=self.root,
        )
        self.root.children.append(self.photo)
        self.snapshot = RecoveryCatalogSnapshot(
            RecoveryCatalog({1: self.root, 2: self.photo}, [self.root]),
            SimpleNamespace(),
        )

    def test_search_matches_names_and_paths_without_case_sensitivity(self):
        matches, total = CatalogService.search(self.snapshot, "summer.jpg")

        self.assertEqual(total, 1)
        self.assertEqual(matches, (self.photo,))

    def test_search_response_includes_parent_id_for_tree_selection(self):
        ids = {id(self.root): "n0", id(self.photo): "n1"}

        response = CatalogMapper.search(self.snapshot, (self.photo,), 1, ids).to_dict()

        self.assertEqual(response["results"][0]["id"], "n1")
        self.assertEqual(response["results"][0]["parentId"], "n0")
        self.assertEqual(response["results"][0]["ancestorIds"], ["n0"])


if __name__ == "__main__":
    unittest.main()
