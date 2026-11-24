import io
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from infrastructure.formats.additional import (
    ADDITIONAL_SIGNATURES,
    COMPOUND_FILE_SIGNATURE,
    RTF_SIGNATURE,
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


def compound_office(kind="word"):
    free = 0xFFFFFFFF
    eoc = 0xFFFFFFFE
    fat_sector = 0xFFFFFFFD
    sector_count = 18
    data = bytearray(512 * (sector_count + 1))
    header = memoryview(data)[:512]
    header[:8] = COMPOUND_FILE_SIGNATURE
    header[24:26] = (0x003E).to_bytes(2, "little")
    header[26:28] = (3).to_bytes(2, "little")
    header[28:30] = b"\xfe\xff"
    header[30:32] = (9).to_bytes(2, "little")
    header[32:34] = (6).to_bytes(2, "little")
    header[44:48] = (1).to_bytes(4, "little")
    header[48:52] = (1).to_bytes(4, "little")
    header[56:60] = (4096).to_bytes(4, "little")
    header[60:64] = eoc.to_bytes(4, "little")
    header[68:72] = eoc.to_bytes(4, "little")
    header[76:80] = (0).to_bytes(4, "little")
    for index in range(80, 512, 4):
        header[index:index + 4] = free.to_bytes(4, "little")

    fat = [free] * 128
    fat[0] = fat_sector
    fat[1] = eoc
    for first in (2, 10):
        for sector in range(first, first + 8):
            fat[sector] = eoc if sector == first + 7 else sector + 1
    data[512:1024] = b"".join(value.to_bytes(4, "little") for value in fat)

    def directory_entry(name, object_type, *, left=free, right=free, child=free,
                        first_sector=eoc, size=0):
        entry = bytearray(128)
        encoded_name = (name + "\0").encode("utf-16le")
        entry[:len(encoded_name)] = encoded_name
        entry[64:66] = len(encoded_name).to_bytes(2, "little")
        entry[66] = object_type
        entry[68:72] = left.to_bytes(4, "little")
        entry[72:76] = right.to_bytes(4, "little")
        entry[76:80] = child.to_bytes(4, "little")
        entry[116:120] = first_sector.to_bytes(4, "little")
        entry[120:128] = size.to_bytes(8, "little")
        return entry

    stream_name = "WordDocument" if kind == "word" else "Workbook"
    table_name = "0Table" if kind == "word" else None
    entries = [directory_entry("Root Entry", 5, child=1)]
    entries.append(directory_entry(stream_name, 2, right=2 if table_name else free,
                                   first_sector=2, size=4096))
    if table_name:
        entries.append(directory_entry(table_name, 2, first_sector=10, size=4096))
    data[1024:1536] = b"".join(entries).ljust(512, b"\0")
    return bytes(data)


class AdditionalFormatValidatorTests(unittest.TestCase):
    def test_signature_contract_covers_ambiguous_zip_and_offset_mp4_markers(self):
        signatures = {(hint, signature, offset) for hint, signature, offset in ADDITIONAL_SIGNATURES}
        self.assertIn(("ooxml", b"PK\x03\x04", 0), signatures)
        self.assertIn(("iso_bmff", b"ftyp", 4), signatures)
        self.assertIn(("rtf", RTF_SIGNATURE, 0), signatures)
        self.assertIn(("ole_compound", COMPOUND_FILE_SIGNATURE, 0), signatures)

        buffer = b"xx" + office_archive() + b"padding" + mp4()
        offsets = find_additional_signatures(buffer)
        self.assertIn(("ooxml", 2), offsets)
        self.assertIn(("iso_bmff", buffer.index(b"ftyp") - 4), offsets)

    def test_detects_balanced_rtf_and_ignores_escaped_or_binary_braces(self):
        candidate = b"{\\rtf1\\ansi\\deff0 Text {nested} \\{escaped\\} \\bin3{}}x}"
        result = validate_additional_candidate(candidate + b"padding")
        self.assertIsNotNone(result)
        self.assertEqual(result.extension, ".rtf")
        self.assertEqual(result.size_bytes, len(candidate))
        self.assertIn("balanced groups", result.validation_scope)

    def test_rejects_truncated_unbalanced_and_excessively_nested_rtf(self):
        self.assertIsNone(validate_additional_candidate(b"{\\rtf1\\ansi text"))
        prefixed = validate_additional_candidate(b"{\\rtf1\\ansi text}}trailing")
        self.assertIsNotNone(prefixed)
        self.assertEqual(prefixed.size_bytes, len(b"{\\rtf1\\ansi text}"))
        deeply_nested = b"{\\rtf1\\ansi" + b"{" * 1025 + b"x" + b"}" * 1026
        self.assertIsNone(validate_additional_candidate(deeply_nested))
        self.assertIsNone(validate_additional_candidate(b"{\\rtf1\\ansi\\bin99x}"))

    def test_detects_legacy_word_and_excel_cfb_by_directory_streams(self):
        for kind, extension in (("word", ".doc"), ("excel", ".xls")):
            with self.subTest(extension=extension):
                candidate = compound_office(kind)
                result = validate_additional_candidate(candidate)
                self.assertIsNotNone(result)
                self.assertEqual(result.extension, extension)
                self.assertEqual(result.size_bytes, len(candidate))
                self.assertIn("FAT/DIFAT bounds", result.validation_scope)

    def test_rejects_truncated_or_corrupted_legacy_office_cfb(self):
        candidate = compound_office("word")
        self.assertIsNone(validate_additional_candidate(candidate[:-1]))
        self.assertIsNone(validate_additional_candidate(candidate[:-512]))
        corrupt_fat = bytearray(candidate)
        corrupt_fat[512:516] = (0xFFFFFFFE).to_bytes(4, "little")
        self.assertIsNone(validate_additional_candidate(bytes(corrupt_fat)))

        generic_ole = bytearray(candidate)
        directory_name_offset = 1024 + 128
        generic_ole[directory_name_offset:directory_name_offset + 24] = (
            "DocumentSummaryInformation\0".encode("utf-16le")[:24]
        )
        self.assertIsNone(validate_additional_candidate(bytes(generic_ole)))

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
