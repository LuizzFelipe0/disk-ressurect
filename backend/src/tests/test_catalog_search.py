import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.catalog.dto import CatalogMapper
from modules.catalog.entities import CatalogNode, RecoveryCatalogSnapshot
from modules.catalog.service import CatalogService
from modules.catalog.entities import RecoveryCatalog
from modules.recovery.entities import RecoveryCandidate


class CatalogSearchTests(unittest.TestCase):
    def setUp(self):
        self.root = CatalogNode("folder-photos", "Photos", "Users/Photos", True, 0)
        candidate = RecoveryCandidate(
            "candidate-photo", "source-test", "volume-test", "Summer.JPG",
            "Users/Photos/Summer.JPG", 128, "synthetic", ("test",), (),
        )
        self.photo = CatalogNode(
            candidate.candidate_id, "Summer.JPG", "Users/Photos/Summer.JPG",
            False, 128, candidate, parent=self.root,
        )
        self.root.children.append(self.photo)
        self.snapshot = RecoveryCatalogSnapshot(
            RecoveryCatalog({self.root.node_id: self.root, self.photo.node_id: self.photo}, [self.root]),
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
