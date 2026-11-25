import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.catalog.mapper import CatalogMapper
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

    def test_search_sorts_and_limits_large_match_sets_while_counting_every_match(self):
        nodes = []
        for index in range(1200):
            name = f"match-{index:04d}.jpg"
            path = f"Users/Photos/{name}"
            candidate = RecoveryCandidate(
                f"candidate-{index}", "source-test", "volume-test", name,
                path, 128, "synthetic", ("test",), (),
            )
            nodes.append(CatalogNode(
                candidate.candidate_id, name, path, False, 128, candidate,
            ))
        snapshot = RecoveryCatalogSnapshot(RecoveryCatalog(nodes))

        matches, total = CatalogService.search(snapshot, "match", limit=500)

        self.assertEqual(total, 1200)
        self.assertEqual(len(matches), 500)
        self.assertEqual(
            [node.full_path for node in matches],
            [f"Users/Photos/match-{index:04d}.jpg" for index in range(500)],
        )

    def test_search_keeps_insertion_order_for_duplicate_sort_keys(self):
        nodes = []
        for index in range(3):
            path = "Users/Photos/match.jpg"
            candidate = RecoveryCandidate(
                f"duplicate-{index}", "source-test", "volume-test", "match.jpg",
                path, 128, "synthetic", ("test",), (),
            )
            nodes.append(CatalogNode(
                candidate.candidate_id, "match.jpg", path, False, 128, candidate,
            ))
        snapshot = RecoveryCatalogSnapshot(RecoveryCatalog(nodes))

        matches, total = CatalogService.search(snapshot, "match", limit=2)

        self.assertEqual(total, 3)
        self.assertEqual([node.node_id for node in matches], ["duplicate-0", "duplicate-1"])

    def test_search_preserves_negative_limit_slice_behavior(self):
        matches, total = CatalogService.search(self.snapshot, "Photos", limit=-1)

        self.assertEqual(total, 2)
        self.assertEqual(matches, (self.root,))

    def test_zero_limit_still_counts_every_match(self):
        matches, total = CatalogService.search(self.snapshot, "Photos", limit=0)

        self.assertEqual(matches, ())
        self.assertEqual(total, 2)


if __name__ == "__main__":
    unittest.main()
