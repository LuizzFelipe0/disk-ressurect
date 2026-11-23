import io
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from disk.deep_scan.additional_format_validators import (
    ADDITIONAL_SIGNATURES,
    find_additional_signatures,
    is_plausible_office_local_header,
    validate_additional_candidate,
)


def office_archive(required_member="word/document.xml", extra_members=()):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for member in ("[Content_Types].xml", "_rels/.rels", required_member, *extra_members):
            archive.writestr(member, b"<root/>" if member.endswith(".xml") else b"macro")
    return stream.getvalue()


def box(kind, payload):
    return (len(payload) + 8).to_bytes(4, "big") + kind + payload


def mp4():
    ftyp = box(b"ftyp", b"isom\x00\x00\x02\x00isom")
    return ftyp + box(b"mdat", b"media") + box(b"moov", b"metadata")


class AdditionalFormatValidatorTests(unittest.TestCase):
    def test_signature_contract_covers_ambiguous_zip_and_offset_mp4_markers(self):
        signatures = {(hint, signature, offset) for hint, signature, offset in ADDITIONAL_SIGNATURES}
        self.assertIn(("ooxml", b"PK\x03\x04", 0), signatures)
        self.assertIn(("iso_bmff", b"ftyp", 4), signatures)

        buffer = b"xx" + office_archive() + b"padding" + mp4()
        offsets = find_additional_signatures(buffer)
        self.assertIn(("ooxml", 2), offsets)
        self.assertIn(("iso_bmff", buffer.index(b"ftyp") - 4), offsets)

    def test_detects_docx_and_xlsx_by_required_member(self):
        for required_member, extension in (
            ("word/document.xml", ".docx"),
            ("xl/workbook.xml", ".xlsx"),
            ("word/document.xml", ".docm"),
            ("xl/workbook.xml", ".xlsm"),
        ):
            with self.subTest(extension=extension):
                macro_member = {
                    ".docm": ("word/vbaProject.bin",),
                    ".xlsm": ("xl/vbaProject.bin",),
                }.get(extension, ())
                candidate = office_archive(required_member, macro_member)
                result = validate_additional_candidate(candidate)
                self.assertIsNotNone(result)
                self.assertEqual(result.extension, extension)
                self.assertEqual(result.size_bytes, len(candidate))
                self.assertIn("central directory", result.validation_scope)

    def test_rejects_generic_zip_without_ooxml_structure(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("notes.txt", b"not an Office document")
        self.assertIsNone(validate_additional_candidate(stream.getvalue()))

    def test_local_header_prefilter_accepts_office_member_and_rejects_generic_zip(self):
        def first_local_header(archive):
            name_length = int.from_bytes(archive[26:28], "little")
            extra_length = int.from_bytes(archive[28:30], "little")
            return archive[:30 + name_length + extra_length]

        office = first_local_header(office_archive())
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("notes.txt", b"not an Office file")
        generic = first_local_header(stream.getvalue())
        self.assertTrue(is_plausible_office_local_header(office))
        self.assertFalse(is_plausible_office_local_header(generic))

    def test_rejects_ooxml_with_corrupt_central_directory_or_truncation(self):
        candidate = bytearray(office_archive())
        central = candidate.index(b"PK\x01\x02")
        candidate[central] = 0
        self.assertIsNone(validate_additional_candidate(bytes(candidate)))
        self.assertIsNone(validate_additional_candidate(office_archive()[:-3]))

    def test_detects_bounded_iso_bmff_mp4_box_chain(self):
        candidate = mp4()
        result = validate_additional_candidate(candidate)
        self.assertIsNotNone(result)
        self.assertEqual(result.extension, ".mp4")
        self.assertEqual(result.size_bytes, len(candidate))
        self.assertIn("top-level box bounds", result.validation_scope)

    def test_rejects_truncated_or_incomplete_iso_bmff(self):
        candidate = mp4()
        self.assertIsNone(validate_additional_candidate(candidate[:-2]))
        self.assertIsNone(validate_additional_candidate(box(b"ftyp", b"isom\x00\x00\x00\x00")))
        malformed = bytearray(candidate)
        malformed[0:4] = (0xFFFFFFFF).to_bytes(4, "big")
        self.assertIsNone(validate_additional_candidate(bytes(malformed)))


if __name__ == "__main__":
    unittest.main()
