import hashlib
import io
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from infrastructure.recovery.extractor import Extractor
from modules.catalog.entities import CatalogNode
from modules.recovery.entities import ContentReference, RecoveryCandidate
from modules.storage.entities import StorageSource


class MemoryContentReader:
    def __init__(self, content_by_reference):
        self.content_by_reference = content_by_reference

    def iter_chunks(self, reference):
        yield self.content_by_reference[reference.reference_id]


def make_node(name, content, full_path=None):
    source_id = "test-source"
    path = full_path or name
    candidate_id = hashlib.sha256(f"{source_id}:{path}".encode()).hexdigest()
    reference = ContentReference(
        candidate_id, source_id, len(content), hashlib.sha256(content).hexdigest(),
    )
    candidate = RecoveryCandidate(
        candidate_id=candidate_id,
        source_id=source_id,
        volume_id="test-volume",
        name=name,
        original_path=path,
        size_bytes=len(content),
        filesystem_id="test-filesystem",
        discovery_methods=("test",),
        evidence=(),
        integrity_state="validated",
        recoverability="recoverable",
        content_reference=reference,
    )
    return CatalogNode(candidate_id, name, path, False, len(content), candidate)


def make_ooxml(member):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(member, "<document/>")
    return payload.getvalue()


def make_mov():
    def box(kind, payload):
        return (len(payload) + 8).to_bytes(4, "big") + kind + payload

    return (box(b"ftyp", b"qt  \x00\x00\x00\x00qt  ")
            + box(b"mdat", b"media") + box(b"moov", b"metadata"))


class ExtractorOfficeFormatTests(unittest.TestCase):
    def make_extractor(self, nodes, contents):
        source = StorageSource("test-source", "raw_image", "test image", 4096, 512, "unused")
        reader = MemoryContentReader({
            node.candidate.content_reference.reference_id: contents[node.name]
            for node in nodes.values() if not node.is_directory
        })
        extractor = Extractor(
            source, nodes, content_reader=reader,
        )
        extractor.set_filters(
            exts=[".pdf", ".doc", ".docx", ".docm", ".rtf", ".xls", ".xlsx", ".xlsm", ".mov"],
            min_kb=0,
        )
        return extractor

    def test_supported_file_types_follow_user_selection_without_folder_blacklists(self):
        names = [
            ("report.pdf", b"%PDF-data"),
            ("legacy.doc", bytes.fromhex("D0CF11E0A1B11AE1")),
            ("modern.docx", make_ooxml("word/document.xml")),
            ("macro.docm", make_ooxml("word/document.xml")),
            ("notes.rtf", b"{\\rtfdata"),
            ("legacy.xls", bytes.fromhex("D0CF11E0A1B11AE1")),
            ("sheet.xlsx", make_ooxml("xl/workbook.xml")),
            ("macro.xlsm", make_ooxml("xl/workbook.xml")),
            ("photo.pdf", b"%PDF-nested"),
        ]
        nodes = {
            str(index): make_node(name, content, "selected-folder/" + name if name == "photo.pdf" else name)
            for index, (name, content) in enumerate(names)
        }
        contents = {node.name: next(payload for name, payload in names if name == node.name)
                    for node in nodes.values()}
        extractor = self.make_extractor(nodes, contents)

        self.assertEqual(len(extractor.candidate_nodes()), len(names))
        extractor.set_filters(exts=[".pdf"], min_kb=0)
        self.assertEqual(
            {node.name for node in extractor.candidate_nodes()},
            {"report.pdf", "photo.pdf"},
        )

    def test_extracts_supported_signatures_and_rejects_mismatch(self):
        contents = {
            "report.pdf": b"%PDF-data",
            "legacy.doc": bytes.fromhex("D0CF11E0A1B11AE1"),
            "modern.docx": make_ooxml("word/document.xml"),
            "macro.docm": make_ooxml("word/document.xml"),
            "notes.rtf": b"{\\rtfdata",
            "legacy.xls": bytes.fromhex("D0CF11E0A1B11AE1"),
            "sheet.xlsx": make_ooxml("xl/workbook.xml"),
            "macro.xlsm": make_ooxml("xl/workbook.xml"),
            "quicktime.mov": make_mov(),
            "broken.xlsx": b"not-a-zip",
        }
        nodes = {name: make_node(name, content) for name, content in contents.items()}
        extractor = self.make_extractor(nodes, contents)

        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with tempfile.TemporaryDirectory(dir=repo_root) as output_dir:
            recovered = extractor.extract(output_dir)
            self.assertEqual(recovered, 9)
            self.assertIn("available signature/container checks", extractor.results[0].reason)
            for name in list(contents)[:-1]:
                with open(os.path.join(output_dir, name), "rb") as recovered_file:
                    self.assertEqual(recovered_file.read(), contents[name])
            self.assertFalse(os.path.exists(os.path.join(output_dir, "broken.xlsx")))

    def test_short_read_is_reported_and_never_published_as_recovered(self):
        content = b"%PDF-complete"
        node = make_node("report.pdf", content)
        extractor = self.make_extractor({"report": node}, {"report.pdf": content})
        extractor.content_reader.content_by_reference[node.candidate.content_reference.reference_id] = b"%PDF"
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        with tempfile.TemporaryDirectory(dir=root) as output_dir:
            recovered = extractor.extract(output_dir)
            self.assertEqual(recovered, 0)
            self.assertEqual(extractor.results[0].status, "incomplete_read")
            self.assertFalse(os.path.exists(os.path.join(output_dir, "report.pdf")))

    def test_checked_folder_expands_to_all_user_selected_type_descendants(self):
        content = b"%PDF-report"
        folder = CatalogNode("folder", "folder", "folder", True, 0)
        child = make_node("inside.pdf", content, "folder/inside.pdf")
        nested = make_node("nested.pdf", content, "selected-folder/nested.pdf")
        folder.children.extend((child, nested))
        child.parent = nested.parent = folder
        nodes = {child.node_id: child, nested.node_id: nested}
        extractor = self.make_extractor(nodes, {"inside.pdf": content, "nested.pdf": content})

        self.assertEqual(extractor.plan_selection([folder]), [child, nested])
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with tempfile.TemporaryDirectory(dir=root) as output_dir:
            recovered = extractor.extract(output_dir, selected_nodes=[folder])
            self.assertEqual(recovered, 2)
            self.assertTrue(os.path.exists(os.path.join(output_dir, "folder", "inside.pdf")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "selected-folder", "nested.pdf")))

    def test_progress_callback_receives_each_result(self):
        content = b"%PDF-report"
        node = make_node("report.pdf", content)
        extractor = self.make_extractor({"report": node}, {"report.pdf": content})
        events = []
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        with tempfile.TemporaryDirectory(dir=root) as output_dir:
            extractor.extract(output_dir, progress_callback=lambda *event: events.append(event))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0:2], (1, 1))
        self.assertEqual(events[0][2].status, "recovered")


if __name__ == "__main__":
    unittest.main()
