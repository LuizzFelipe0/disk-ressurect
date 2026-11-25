import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from application.session import RecoverySession


class RecoverySessionTests(unittest.TestCase):
    def test_session_reuses_catalog_node_dictionary_without_a_persistent_identity_index(self):
        first_node = SimpleNamespace(node_id="first")
        nodes = {"first": first_node}
        first_snapshot = SimpleNamespace(
            catalog=SimpleNamespace(nodes=nodes),
        )
        session = RecoverySession()

        first_index = session.set_catalog(first_snapshot)

        self.assertIs(session.node_ids_by_identity(), first_index)
        self.assertEqual(first_index, {})
        self.assertIs(session.nodes, nodes)
        self.assertIs(session.get_node("first"), first_node)


if __name__ == "__main__":
    unittest.main()
