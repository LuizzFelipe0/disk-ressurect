import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from infrastructure.recovery.extractor import Extractor
from modules.catalog.entities import CatalogNode, RecoveryCatalog
from modules.recovery.entities import ContentReference, RecoveryCandidate
from modules.storage.entities import StorageSource


class SyntheticFilesystemAdapter:
    """Test-only adapter that emits candidates without filesystem metadata."""

    def __init__(self, source):
        self.source = source

    def catalog(self, path, payload):
        digest = hashlib.sha256(payload).hexdigest()
        candidate_id = hashlib.sha256(
            f"{self.source.source_id}:{path}:{digest}".encode(),
        ).hexdigest()
        reference = ContentReference(candidate_id, self.source.source_id, len(payload), digest)
        candidate = RecoveryCandidate(
            candidate_id=candidate_id,
            source_id=self.source.source_id,
            volume_id="synthetic-volume",
            name=Path(path).name,
            original_path=path,
            size_bytes=len(payload),
            filesystem_id="synthetic-test",
            discovery_methods=("synthetic_test",),
            evidence=(),
            integrity_state="validated",
            recoverability="recoverable",
            content_reference=reference,
        )
        return CatalogNode(candidate_id, Path(path).name, path, False, len(payload), candidate)


class SyntheticContentReader:
    def __init__(self, payloads):
        self.payloads = payloads

    def iter_chunks(self, reference):
        yield self.payloads[reference.reference_id]


class FilesystemNeutralRecoveryTests(unittest.TestCase):
    def test_catalog_selection_and_extraction_do_not_require_ntfs_or_partition_metadata(self):
        source = StorageSource("test-image:one", "raw_image", "test image", 4096, 512, "unused")
        adapter = SyntheticFilesystemAdapter(source)
        payloads = {
            "docs/report.pdf": b"%PDF-1.4 test data",
            "docs/readme.txt": b"not selected by supported format",
        }
        nodes = [adapter.catalog(path, payload) for path, payload in payloads.items()]
        folder = CatalogNode("folder:docs", "docs", "docs", True, 0)
        folder.children.extend(nodes)
        for node in nodes:
            node.parent = folder
        catalog = RecoveryCatalog({node.node_id: node for node in [folder, *nodes]}, [folder])
        reader = SyntheticContentReader({
            node.candidate.candidate_id: payloads[node.full_path] for node in nodes
        })
        extractor = Extractor(source, catalog.nodes, root_nodes=[folder], content_reader=reader)
        extractor.set_filters({".pdf"})

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with tempfile.TemporaryDirectory(dir=root) as output:
            self.assertEqual(extractor.plan_selection([folder]), [nodes[0]])
            self.assertEqual(extractor.extract(output, selected_nodes=[folder]), 1)
            self.assertEqual(
                (Path(output) / "docs" / "report.pdf").read_bytes(),
                payloads["docs/report.pdf"],
            )

    def test_content_digest_mismatch_is_never_published(self):
        source = StorageSource("test-image:two", "raw_image", "test image", 4096, 512, "unused")
        adapter = SyntheticFilesystemAdapter(source)
        node = adapter.catalog("photo.jpg", b"\xff\xd8\xfforiginal")
        reader = SyntheticContentReader({node.candidate.candidate_id: b"\xff\xd8\xffchanged!"})
        extractor = Extractor(source, {node.node_id: node}, content_reader=reader)

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with tempfile.TemporaryDirectory(dir=root) as output:
            self.assertEqual(extractor.extract(output), 0)
            self.assertEqual(extractor.results[0].status, "content_mismatch")
            self.assertEqual(list(Path(output).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
