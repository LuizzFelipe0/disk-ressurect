import contextlib
import io
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ntfs.extractor import Extractor


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
    )


class ExtractorOfficeFormatTests(unittest.TestCase):
    def make_extractor(self, nodes, contents):
        # Use 4-byte clusters so the tests do not allocate large buffers.
        required_size = 0
        for node in nodes.values():
            lcn = node.record.data_runs[0][0]
            content = contents[node.record.name]
            required_size = max(required_size, lcn * 4 + len(content))
        disk_data = bytearray(required_size)
        for node in nodes.values():
            lcn = node.record.data_runs[0][0]
            content = contents[node.record.name]
            disk_data[lcn * 4:lcn * 4 + len(content)] = content
        extractor = Extractor(FakeDisk(bytes(disk_data)), nodes, vol_start=0, cluster_size=4)
        extractor.set_filters(
            exts=['.pdf', '.doc', '.docx', '.docm', '.rtf', '.xls', '.xlsx', '.xlsm'],
            dirs=['windows', 'program files', 'bkp fotos notebook'],
            min_kb=0,
        )
        return extractor

    def test_office_and_pdf_extensions_are_selected_but_overwritten_folder_is_excluded(self):
        included = [
            make_node('report.pdf', b'%PDFdata'),
            make_node('legacy.doc', bytes.fromhex('D0CF11E0A1B11AE1')),
            make_node('modern.docx', b'PK\x03\x04data'),
            make_node('macro.docm', b'PK\x03\x04data'),
            make_node('notes.rtf', b'{\\rtfdata'),
            make_node('legacy.xls', bytes.fromhex('D0CF11E0A1B11AE1')),
            make_node('sheet.xlsx', b'PK\x03\x04data'),
            make_node('macro.xlsm', b'PK\x03\x04data'),
        ]
        excluded = make_node(
            'photo.pdf', b'%PDFdata',
            full_path='bkp fotos notebook\\photo.pdf',
        )
        extractor = self.make_extractor({}, {})

        self.assertTrue(all(extractor._should_extract(node) for node in included))
        self.assertFalse(extractor._should_extract(excluded))

    def test_extracts_supported_signatures_and_rejects_mismatch(self):
        contents = {
            'report.pdf': b'%PDFdata',
            'legacy.doc': bytes.fromhex('D0CF11E0A1B11AE1'),
            'modern.docx': b'PK\x03\x04data',
            'macro.docm': b'PK\x03\x04data',
            'notes.rtf': b'{\\rtfdata',
            'legacy.xls': bytes.fromhex('D0CF11E0A1B11AE1'),
            'sheet.xlsx': b'PK\x03\x04data',
            'macro.xlsm': b'PK\x03\x04data',
            'broken.xlsx': b'not-a-zip',
        }
        nodes = {
            name: make_node(name, content, lcn=index * 4)
            for index, (name, content) in enumerate(contents.items(), 1)
        }
        extractor = self.make_extractor(nodes, contents)

        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        with tempfile.TemporaryDirectory(dir=repo_root) as output_dir:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                recovered = extractor.extract(output_dir)

            self.assertEqual(recovered, 8)
            self.assertIn('100%', output.getvalue())
            for name in list(contents)[:-1]:
                with open(os.path.join(output_dir, name), 'rb') as recovered_file:
                    self.assertEqual(recovered_file.read(), contents[name])
            self.assertFalse(os.path.exists(os.path.join(output_dir, 'broken.xlsx')))


if __name__ == '__main__':
    unittest.main()
