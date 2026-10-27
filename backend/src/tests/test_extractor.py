import io
import os
import sys
import tempfile
import unittest
import zipfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from modules.recovery.extractor import Extractor


class FakeDisk:
    def __init__(self, data):
        self.data = data

    def read_at(self, offset, size):
        return self.data[offset:offset + size]


def make_node(name, content, full_path=None, lcn=1):
    record = SimpleNamespace(
        name=name,
        is_dir=False,
        file_size=len(content),
        resident_data=None,
        data_runs=[(lcn, (len(content) + 3) // 4)],
    )
    return SimpleNamespace(
        record=record,
        full_path=full_path or name,
        children=[],
        parent=None,
    )


def make_ooxml(member):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(member, "<document/>")
    return payload.getvalue()


class ExtractorOfficeFormatTests(unittest.TestCase):
    def make_extractor(self, nodes, contents):
        # Use 4-byte clusters so the tests do not allocate large buffers.
        required_size = 0
        next_lcn = 1
        for node in nodes.values():
            content = contents[node.record.name]
            lcn = next_lcn
            cluster_count = (len(content) + 3) // 4
            node.record.data_runs = [(lcn, cluster_count)]
            next_lcn += cluster_count + 2
            required_size = max(required_size, lcn * 4 + len(content))
        disk_data = bytearray(required_size)
        for node in nodes.values():
            lcn = node.record.data_runs[0][0]
            content = contents[node.record.name]
            disk_data[lcn * 4:lcn * 4 + len(content)] = content
        extractor = Extractor(FakeDisk(bytes(disk_data)), nodes, vol_start=0, cluster_size=4)
        extractor.set_filters(
            exts=['.pdf', '.doc', '.docx', '.docm', '.rtf', '.xls', '.xlsx', '.xlsm'],
            min_kb=0,
        )
        return extractor

    def test_supported_file_types_follow_user_selection_without_folder_blacklists(self):
        included = [
            make_node('report.pdf', b'%PDF-data'),
            make_node('legacy.doc', bytes.fromhex('D0CF11E0A1B11AE1')),
            make_node('modern.docx', make_ooxml('word/document.xml')),
            make_node('macro.docm', make_ooxml('word/document.xml')),
            make_node('notes.rtf', b'{\\rtfdata'),
            make_node('legacy.xls', bytes.fromhex('D0CF11E0A1B11AE1')),
            make_node('sheet.xlsx', make_ooxml('xl/workbook.xml')),
            make_node('macro.xlsm', make_ooxml('xl/workbook.xml')),
        ]
        nested = make_node(
            'photo.pdf', b'%PDF-data',
            full_path='user-selected-folder\\photo.pdf',
        )
        nodes = {str(index): node for index, node in enumerate([*included, nested])}
        contents = {node.record.name: b'%PDF-data' for node in [*included, nested]}
        contents.update({node.record.name: bytes([index]) * 16 for index, node in enumerate(included)})
        extractor = self.make_extractor(nodes, contents)

        self.assertEqual(len(extractor.candidate_nodes()), len(included) + 1)
        extractor.set_filters(exts=['.pdf'], min_kb=0)
        self.assertEqual(
            {node.record.name for node in extractor.candidate_nodes()},
            {"report.pdf", "photo.pdf"},
        )

    def test_extracts_supported_signatures_and_rejects_mismatch(self):
        contents = {
            'report.pdf': b'%PDF-data',
            'legacy.doc': bytes.fromhex('D0CF11E0A1B11AE1'),
            'modern.docx': make_ooxml('word/document.xml'),
            'macro.docm': make_ooxml('word/document.xml'),
            'notes.rtf': b'{\\rtfdata',
            'legacy.xls': bytes.fromhex('D0CF11E0A1B11AE1'),
            'sheet.xlsx': make_ooxml('xl/workbook.xml'),
            'macro.xlsm': make_ooxml('xl/workbook.xml'),
            'broken.xlsx': b'not-a-zip',
        }
        nodes = {
            name: make_node(name, content, lcn=index * 4)
            for index, (name, content) in enumerate(contents.items(), 1)
        }
        extractor = self.make_extractor(nodes, contents)

        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        with tempfile.TemporaryDirectory(dir=repo_root) as output_dir:
            recovered = extractor.extract(output_dir)

            self.assertEqual(recovered, 8)
            self.assertIn("available signature/container checks", extractor.results[0].reason)
            for name in list(contents)[:-1]:
                with open(os.path.join(output_dir, name), 'rb') as recovered_file:
                    self.assertEqual(recovered_file.read(), contents[name])
            self.assertFalse(os.path.exists(os.path.join(output_dir, 'broken.xlsx')))

    def test_short_disk_read_is_reported_and_never_published_as_recovered(self):
        content = b"%PDF-complete"
        node = make_node('report.pdf', content)
        extractor = self.make_extractor({'report': node}, {'report.pdf': content})
        extractor.content_reader.disk = FakeDisk(b"%PDF")
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

        with tempfile.TemporaryDirectory(dir=root) as output_dir:
            recovered = extractor.extract(output_dir)
            self.assertEqual(recovered, 0)
            self.assertEqual(extractor.results[0].status, 'incomplete_read')
            self.assertFalse(os.path.exists(os.path.join(output_dir, 'report.pdf')))

    def test_checked_folder_expands_to_all_user_selected_type_descendants(self):
        content = b"%PDF-report"
        folder = make_node('folder', b'', full_path='folder')
        folder.record.is_dir = True
        child = make_node('inside.pdf', content, full_path=os.path.join('folder', 'inside.pdf'))
        child.record.data_runs = [(2, (len(content) + 3) // 4)]
        child.parent = folder
        folder.children.append(child)
        nested = make_node('nested.pdf', content, full_path=os.path.join('selected folder', 'nested.pdf'))
        nested.parent = folder
        folder.children.append(nested)
        nodes = {'child': child, 'nested': nested}
        extractor = self.make_extractor(nodes, {'inside.pdf': content, 'nested.pdf': content})

        self.assertEqual(extractor.plan_selection([folder]), [child, nested])
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        with tempfile.TemporaryDirectory(dir=root) as output_dir:
            recovered = extractor.extract(output_dir, selected_nodes=[folder])
            self.assertEqual(recovered, 2)
            self.assertTrue(os.path.exists(os.path.join(output_dir, 'folder', 'inside.pdf')))
            self.assertTrue(os.path.exists(os.path.join(output_dir, 'selected folder', 'nested.pdf')))

    def test_progress_callback_receives_each_result(self):
        content = b"%PDF-report"
        node = make_node('report.pdf', content)
        extractor = self.make_extractor({'report': node}, {'report.pdf': content})
        events = []
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

        with tempfile.TemporaryDirectory(dir=root) as output_dir:
            extractor.extract(output_dir, progress_callback=lambda *event: events.append(event))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0:2], (1, 1))
        self.assertEqual(events[0][2].status, 'recovered')


if __name__ == '__main__':
    unittest.main()
