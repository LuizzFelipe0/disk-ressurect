import os
import sys
import unittest
import io
import struct
import tempfile
import zlib
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from infrastructure.carving.content_carver import RawContentCarver
from infrastructure.filesystems.ntfs.readers.file_signature_validator import FileSignatureValidator
from infrastructure.carving.validators.additional import COMPOUND_FILE_SIGNATURE
from modules.recovery.extractor import Extractor


def jpeg(payload=b"entropy-data"):
    # Minimal marker-valid baseline JPEG for deterministic parser tests.
    return (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x04\x00\x00"
        + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        + payload.replace(b"\xff", b"\xff\x00")
        + b"\xff\xd9"
    )


def png():
    def chunk(kind, payload):
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
            + chunk(b"IEND", b""))


def pdf():
    prefix = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    xref_offset = len(prefix)
    object_offset = len(b"%PDF-1.4\n")
    return (prefix + b"xref\n0 2\n0000000000 65535 f \n"
            + f"{object_offset:010d} 00000 n \n".encode("ascii")
            + b"trailer\n<< /Size 2 /Root 1 0 R >>\n"
            + b"startxref\n" + str(xref_offset).encode("ascii") + b"\n%%EOF\n")


def office_zip(required_member="word/document.xml", extra_members=()):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for member in ("[Content_Types].xml", "_rels/.rels", required_member, *extra_members):
            archive.writestr(member, b"<root/>" if member.endswith(".xml") else b"macro")
    return stream.getvalue()


def mp4():
    def box(kind, payload):
        return (len(payload) + 8).to_bytes(4, "big") + kind + payload

    return (box(b"ftyp", b"isom\x00\x00\x02\x00isom")
            + box(b"mdat", b"media") + box(b"moov", b"metadata"))


def compound_office(kind="word"):
    free, eoc, fat_sector = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
    data = bytearray(512 * 19)
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

    def entry(name, object_type, *, right=free, child=free, first_sector=eoc, size=0):
        value = bytearray(128)
        encoded = (name + "\0").encode("utf-16le")
        value[:len(encoded)] = encoded
        value[64:66] = len(encoded).to_bytes(2, "little")
        value[66] = object_type
        value[68:72] = free.to_bytes(4, "little")
        value[72:76] = right.to_bytes(4, "little")
        value[76:80] = child.to_bytes(4, "little")
        value[116:120] = first_sector.to_bytes(4, "little")
        value[120:128] = size.to_bytes(8, "little")
        return value

    main_name = "WordDocument" if kind == "word" else "Workbook"
    entries = [entry("Root Entry", 5, child=1)]
    entries.append(entry(main_name, 2, right=2 if kind == "word" else free,
                         first_sector=2, size=4096))
    if kind == "word":
        entries.append(entry("0Table", 2, first_sector=10, size=4096))
    data[1024:1536] = b"".join(entries).ljust(512, b"\0")
    return bytes(data)


class FakeDisk:
    def __init__(self, size=4096, *, short_reads=False):
        self.data = bytearray(size)
        self.size = size
        self.short_reads = short_reads
        self.reads = []

    def read_at(self, offset, size):
        self.reads.append((offset, size))
        end = min(offset + size, self.size)
        if self.short_reads and end > offset:
            end -= 1
        return bytes(self.data[offset:end])


class RawContentCarverTests(unittest.TestCase):
    def test_carver_output_extensions_are_supported_by_extractor_and_signature_validator(self):
        carved_extensions = {
            extension
            for extensions in RawContentCarver.EXTENSIONS_BY_FAMILY.values()
            for extension in extensions
        }
        extractor_extensions = set(Extractor.supported_extensions())
        signature_extensions = set(FileSignatureValidator.supported_extensions())

        self.assertEqual(extractor_extensions, signature_extensions)
        self.assertTrue(carved_extensions)
        self.assertLessEqual(carved_extensions, extractor_extensions)

    def test_finds_complete_jpeg_across_scan_chunk_boundary(self):
        disk = FakeDisk()
        candidate = jpeg()
        disk.data[511:511 + len(candidate)] = candidate
        progress = []

        result = RawContentCarver(disk, chunk_size=512).scan(
            [(0, disk.size)], progress_callback=lambda done, total: progress.append((done, total)),
        )

        self.assertEqual(len(result.files), 1)
        self.assertEqual(result.files[0].offset, 511)
        self.assertEqual(result.files[0].extension, ".jpg")
        self.assertEqual(result.files[0].data, candidate)
        self.assertEqual(result.files[0].size_bytes, len(candidate))
        self.assertEqual(progress[-1], (disk.size, disk.size))
        self.assertFalse(result.scan_limit_reached)

    def test_recovers_structurally_valid_png_and_reports_format_counts(self):
        disk = FakeDisk()
        candidate = png()
        disk.data[128:128 + len(candidate)] = candidate

        result = RawContentCarver(disk, chunk_size=512).scan([(0, disk.size)])

        self.assertEqual([(item.extension, item.data) for item in result.files], [(".png", candidate)])
        stats = {item.extension: item for item in result.format_stats}
        self.assertEqual(stats[".png"].candidates_examined, 1)
        self.assertEqual(stats[".png"].files_found, 1)
        self.assertGreater(stats[".png"].candidate_bytes_read, 0)

    def test_finds_png_and_pdf_signatures_across_scan_chunk_boundaries(self):
        for candidate, extension in ((png(), ".png"), (pdf(), ".pdf")):
            with self.subTest(extension=extension):
                disk = FakeDisk()
                disk.data[509:509 + len(candidate)] = candidate

                result = RawContentCarver(disk, chunk_size=512).scan([(0, disk.size)])

                self.assertEqual([item.extension for item in result.files], [extension])
                self.assertEqual(result.files[0].offset, 509)

    def test_finds_office_zip_signature_across_scan_chunk_boundary_and_reports_family(self):
        disk = FakeDisk(size=4096)
        candidate = office_zip()
        disk.data[511:511 + len(candidate)] = candidate

        result = RawContentCarver(disk, chunk_size=512).scan([(0, disk.size)])

        self.assertEqual([(item.offset, item.extension, item.data) for item in result.files],
                         [(511, ".docx", candidate)])
        stats = {item.extension: item for item in result.format_stats}
        self.assertEqual(stats[".office_zip"].candidates_examined, 1)
        self.assertEqual(stats[".office_zip"].files_found, 1)
        self.assertGreater(stats[".office_zip"].candidate_bytes_read, 0)

    def test_rejects_false_office_header_before_reading_a_large_candidate(self):
        disk = FakeDisk(size=4096)
        disk.data[128:132] = b"PK\x03\x04"

        result = RawContentCarver(disk).scan([(0, disk.size)])

        stats = {item.extension: item for item in result.format_stats}
        self.assertEqual(result.files, ())
        self.assertEqual(stats[".office_zip"].candidates_examined, 1)
        self.assertEqual(stats[".office_zip"].candidate_bytes_read, 30)
        self.assertFalse(stats[".office_zip"].candidate_limit_reached)
        self.assertFalse(stats[".office_zip"].file_size_limit_reached)

    def test_detects_docm_xlsx_and_xlsm_extensions_from_ooxml_members(self):
        variants = (
            ("word/document.xml", ("word/vbaProject.bin",), ".docm"),
            ("xl/workbook.xml", (), ".xlsx"),
            ("xl/workbook.xml", ("xl/vbaProject.bin",), ".xlsm"),
        )
        for required_member, extra_members, extension in variants:
            with self.subTest(extension=extension):
                disk = FakeDisk()
                candidate = office_zip(required_member, extra_members)
                disk.data[128:128 + len(candidate)] = candidate

                result = RawContentCarver(disk).scan([(0, disk.size)])

                self.assertEqual([item.extension for item in result.files], [extension])

    def test_carved_office_and_mp4_candidates_pass_existing_recovery_signature_rules(self):
        candidates = (
            (office_zip(), ".docx"),
            (office_zip("word/document.xml", ("word/vbaProject.bin",)), ".docm"),
            (office_zip("xl/workbook.xml"), ".xlsx"),
            (office_zip("xl/workbook.xml", ("xl/vbaProject.bin",)), ".xlsm"),
            (mp4(), ".mp4"),
        )
        for candidate, extension in candidates:
            with self.subTest(extension=extension), tempfile.TemporaryDirectory() as directory:
                recovered_path = os.path.join(directory, "recovered" + extension)
                with open(recovered_path, "wb") as recovered:
                    recovered.write(candidate)
                header = candidate[:FileSignatureValidator.header_window(extension)]
                self.assertTrue(FileSignatureValidator.matches(extension, header))
                self.assertEqual(
                    FileSignatureValidator.validate_container(recovered_path, extension, header),
                    "",
                )

    def test_finds_mp4_ftyp_marker_at_offset_four_across_scan_chunk_boundary(self):
        disk = FakeDisk(size=4096)
        candidate = mp4()
        disk.data[509:509 + len(candidate)] = candidate

        result = RawContentCarver(disk, chunk_size=512).scan([(0, disk.size)])

        self.assertEqual([(item.offset, item.extension, item.data) for item in result.files],
                         [(509, ".mp4", candidate)])
        stats = {item.extension: item for item in result.format_stats}
        self.assertEqual(stats[".mp4"].candidates_examined, 1)
        self.assertEqual(stats[".mp4"].files_found, 1)

    def test_finds_rtf_across_scan_boundary_and_cfb_office_candidate(self):
        fixtures = (
            (b"{\\rtf1\\ansi\\deff0 Hello {there}.}", 510, ".rtf"),
            (compound_office("word"), 509, ".doc"),
            (compound_office("excel"), 127, ".xls"),
        )
        for candidate, offset, extension in fixtures:
            with self.subTest(extension=extension):
                disk = FakeDisk(size=20_480)
                disk.data[offset:offset + len(candidate)] = candidate

                result = RawContentCarver(disk, chunk_size=512).scan([(0, disk.size)])

                self.assertEqual([(item.offset, item.extension, item.data) for item in result.files],
                                 [(offset, extension, candidate)])
                stats = {item.extension: item for item in result.format_stats}
                family = ".rtf" if extension == ".rtf" else ".ole_cfb"
                self.assertEqual(stats[family].candidates_examined, 1)
                self.assertEqual(stats[family].files_found, 1)

    def test_carved_rtf_doc_and_xls_pass_existing_recovery_signature_rules(self):
        candidates = (
            (b"{\\rtf1\\ansi Example}", ".rtf"),
            (compound_office("word"), ".doc"),
            (compound_office("excel"), ".xls"),
        )
        for candidate, extension in candidates:
            with self.subTest(extension=extension), tempfile.TemporaryDirectory() as directory:
                disk = FakeDisk(size=max(4096, len(candidate) + 512))
                disk.data[128:128 + len(candidate)] = candidate
                carved = RawContentCarver(disk).scan([(0, disk.size)]).files[0]
                self.assertEqual(carved.extension, extension)

                recovered_path = os.path.join(directory, "recovered" + extension)
                with open(recovered_path, "wb") as output:
                    output.write(carved.data)
                header = carved.data[:FileSignatureValidator.header_window(extension)]
                self.assertTrue(FileSignatureValidator.matches(extension, header))
                self.assertEqual(
                    FileSignatureValidator.validate_container(recovered_path, extension, header),
                    "",
                )

    def test_new_format_families_have_independent_candidate_read_budgets(self):
        disk = FakeDisk(size=4096)
        office = office_zip()
        media = mp4()
        disk.data[128:128 + len(office)] = office
        disk.data[1024:1024 + len(media)] = media

        result = RawContentCarver(
            disk, max_candidate_read_bytes=4096, max_candidate_read_bytes_per_format=16,
        ).scan([(0, disk.size)])

        stats = {item.extension: item for item in result.format_stats}
        self.assertEqual(result.files, ())
        self.assertEqual(stats[".office_zip"].candidate_bytes_read, 16)
        self.assertEqual(stats[".mp4"].candidate_bytes_read, 8)
        self.assertTrue(stats[".office_zip"].candidate_limit_reached)
        self.assertTrue(stats[".mp4"].candidate_limit_reached)
        self.assertFalse(result.candidate_limit_reached)

    def test_resume_restores_ooxml_candidates_using_the_updated_scan_profile(self):
        disk = FakeDisk(size=4096)
        candidate = office_zip()
        disk.data[128:128 + len(candidate)] = candidate
        first = RawContentCarver(disk, chunk_size=512, max_scan_bytes=1024).scan(
            [(0, disk.size)],
        )
        self.assertEqual(first.files[0].extension, ".docx")
        self.assertEqual(first.checkpoint.candidates[0].extension, ".docx")

        disk.reads.clear()
        resumed = RawContentCarver(disk, chunk_size=512, max_scan_bytes=512).scan(
            [(0, disk.size)], resume_checkpoint=first.checkpoint,
        )

        self.assertEqual(resumed.files[0].data, candidate)
        self.assertGreater(resumed.candidate_restore_bytes_read, 0)
        self.assertTrue(all(
            offset >= first.checkpoint.next_offset or 128 <= offset < 128 + len(candidate)
            for offset, _ in disk.reads
        ))

    def test_resume_restores_mp4_candidates_by_supported_extension(self):
        disk = FakeDisk(size=4096)
        candidate = mp4()
        disk.data[128:128 + len(candidate)] = candidate
        first = RawContentCarver(disk, chunk_size=512, max_scan_bytes=1024).scan(
            [(0, disk.size)],
        )
        self.assertEqual(first.files[0].extension, ".mp4")
        self.assertEqual(first.checkpoint.candidates[0].extension, ".mp4")

        disk.reads.clear()
        resumed = RawContentCarver(disk, chunk_size=512, max_scan_bytes=512).scan(
            [(0, disk.size)], resume_checkpoint=first.checkpoint,
        )

        self.assertEqual(resumed.files[0].data, candidate)
        self.assertGreater(resumed.candidate_restore_bytes_read, 0)
        self.assertTrue(all(
            offset >= first.checkpoint.next_offset or 128 <= offset < 128 + len(candidate)
            for offset, _ in disk.reads
        ))

    def test_new_format_candidate_bytes_obey_the_file_size_cap(self):
        for candidate, family in ((office_zip(), ".office_zip"), (mp4(), ".mp4")):
            with self.subTest(family=family):
                disk = FakeDisk(size=4096)
                disk.data[128:128 + len(candidate)] = candidate

                result = RawContentCarver(
                    disk, max_file_bytes=32, max_candidate_read_bytes=4096,
                ).scan([(0, disk.size)])

                stats = {item.extension: item for item in result.format_stats}
                self.assertNotIn(family, [item.extension for item in result.files])
                self.assertTrue(stats[family].file_size_limit_reached)

    def test_rejects_png_with_bad_chunk_crc(self):
        disk = FakeDisk()
        candidate = bytearray(png())
        candidate[-5] ^= 0x01
        disk.data[128:128 + len(candidate)] = candidate

        result = RawContentCarver(disk).scan([(0, disk.size)])

        self.assertNotIn(".png", [item.extension for item in result.files])

    def test_recovers_pdf_with_valid_startxref_target_and_eof(self):
        disk = FakeDisk()
        candidate = pdf()
        disk.data[128:128 + len(candidate)] = candidate

        result = RawContentCarver(disk, chunk_size=512).scan([(0, disk.size)])

        self.assertEqual([(item.extension, item.data) for item in result.files], [(".pdf", candidate.rstrip())])
        stats = {item.extension: item for item in result.format_stats}
        self.assertEqual(stats[".pdf"].candidates_examined, 1)
        self.assertEqual(stats[".pdf"].files_found, 1)

    def test_rejects_pdf_without_valid_xref_reference(self):
        disk = FakeDisk()
        candidate = b"%PDF-1.4\nnot a document\nstartxref\n400\n%%EOF"
        disk.data[128:128 + len(candidate)] = candidate

        result = RawContentCarver(disk).scan([(0, disk.size)])

        self.assertNotIn(".pdf", [item.extension for item in result.files])

    def test_rejects_pdf_with_xref_keyword_but_malformed_subsection(self):
        disk = FakeDisk()
        prefix = b"%PDF-1.4\nxref\nthis-is-not-a-subsection\ntrailer\n<< /Size 2 /Root 1 0 R >>\n"
        xref_offset = prefix.index(b"xref")
        candidate = prefix + b"startxref\n" + str(xref_offset).encode("ascii") + b"\n%%EOF"
        disk.data[128:128 + len(candidate)] = candidate

        result = RawContentCarver(disk).scan([(0, disk.size)])

        self.assertNotIn(".pdf", [item.extension for item in result.files])

    def test_jpeg_candidate_budget_does_not_starve_png_or_pdf(self):
        disk = FakeDisk(size=8192)
        disk.data[128:131] = b"\xff\xd8\xff"
        disk.data[1024:1027] = b"\xff\xd8\xff"
        disk.data[1536:1539] = b"\xff\xd8\xff"
        disk.data[2560:2563] = b"\xff\xd8\xff"
        disk.data[3584:3587] = b"\xff\xd8\xff"
        png_candidate = png()
        pdf_candidate = pdf()
        disk.data[2048:2048 + len(png_candidate)] = png_candidate
        disk.data[4096:4096 + len(pdf_candidate)] = pdf_candidate

        result = RawContentCarver(
            disk,
            chunk_size=512,
            max_candidate_read_bytes=8192,
            max_candidate_read_bytes_per_format=2048,
        ).scan([(0, disk.size)])

        self.assertEqual({item.extension for item in result.files}, {".png", ".pdf"})
        stats = {item.extension: item for item in result.format_stats}
        self.assertTrue(stats[".jpg"].candidate_limit_reached)
        self.assertFalse(stats[".png"].candidate_limit_reached)
        self.assertFalse(stats[".pdf"].candidate_limit_reached)
        self.assertFalse(result.candidate_limit_reached)

    def test_reports_per_file_size_limit_without_counting_a_candidate_as_found(self):
        disk = FakeDisk(size=4096)
        partial = jpeg()[:-2] + bytes(1024)
        disk.data[128:128 + len(partial)] = partial

        result = RawContentCarver(
            disk, max_file_bytes=512, max_candidate_read_bytes=4096,
        ).scan([(0, disk.size)])

        stats = {item.extension: item for item in result.format_stats}
        self.assertEqual(result.files, ())
        self.assertTrue(stats[".jpg"].file_size_limit_reached)
        self.assertFalse(stats[".jpg"].candidate_limit_reached)

    def test_reports_png_decompressed_output_limit(self):
        disk = FakeDisk()
        candidate = png()
        disk.data[128:128 + len(candidate)] = candidate

        result = RawContentCarver(disk, max_decoded_png_bytes=4).scan([(0, disk.size)])

        stats = {item.extension: item for item in result.format_stats}
        self.assertEqual(result.files, ())
        self.assertTrue(stats[".png"].decoded_data_limit_reached)

    def test_rejects_truncated_or_malformed_jpeg_candidates(self):
        disk = FakeDisk()
        malformed = b"\xff\xd8\xff\xe0\x00\x01not-a-jpeg\xff\xd9"
        disk.data[100:100 + len(malformed)] = malformed
        disk.data[500:510] = b"\xff\xd8\xffgarbage"

        result = RawContentCarver(disk, chunk_size=512).scan([(0, 1024)])

        self.assertEqual(result.files, ())

    def test_ignores_eoi_bytes_inside_length_delimited_app_segment(self):
        disk = FakeDisk()
        candidate = b"\xff\xd8\xff\xe1\x00\x06\xff\xd9\x00\x00" + jpeg()[2:]
        disk.data[128:128 + len(candidate)] = candidate

        result = RawContentCarver(disk, chunk_size=512).scan([(0, disk.size)])

        self.assertEqual(len(result.files), 1)
        self.assertEqual(result.files[0].data, candidate)

    def test_merges_overlapping_ranges_and_deduplicates_same_content(self):
        disk = FakeDisk(size=2048)
        candidate = jpeg(b"same")
        disk.data[100:100 + len(candidate)] = candidate
        disk.data[700:700 + len(candidate)] = candidate

        result = RawContentCarver(disk).scan([(0, 500), (400, 1000), (900, 1500)])

        self.assertEqual([item.offset for item in result.files], [100])
        self.assertEqual(result.bytes_scanned, 1500)

    def test_reports_scan_budget_and_candidate_read_budget(self):
        disk = FakeDisk(size=4096)
        candidate = jpeg()
        disk.data[100:100 + len(candidate)] = candidate

        result = RawContentCarver(
            disk,
            chunk_size=512,
            max_scan_bytes=1024,
            max_candidate_read_bytes=len(candidate) - 1,
        ).scan([(0, disk.size)])

        self.assertTrue(result.scan_limit_reached)
        self.assertTrue(result.candidate_limit_reached)
        self.assertEqual(result.bytes_scanned, 100)
        self.assertEqual(result.candidate_bytes_read, len(candidate) - 1)
        self.assertEqual(result.files, ())

    def test_resumes_after_scan_budget_without_repeating_completed_ranges(self):
        disk = FakeDisk(size=4096)
        candidate = jpeg()
        disk.data[100:100 + len(candidate)] = candidate
        first = RawContentCarver(disk, chunk_size=512, max_scan_bytes=1024).scan(
            [(0, disk.size)],
        )
        checkpoint = first.checkpoint
        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint.next_offset, 1024)
        self.assertEqual(first.files[0].data, candidate)

        disk.reads.clear()
        resumed = RawContentCarver(disk, chunk_size=512, max_scan_bytes=1024).scan(
            [(0, disk.size)], resume_checkpoint=checkpoint,
        )

        self.assertEqual(resumed.files, (first.files[0],))
        self.assertEqual(resumed.checkpoint.next_offset, 2048)
        self.assertEqual(resumed.checkpoint.bytes_scanned, 2048)
        self.assertEqual(resumed.cumulative_bytes_scanned, 2048)
        scan_reads = [offset for offset, _ in disk.reads if offset >= 1024]
        self.assertTrue(scan_reads)
        self.assertNotIn(0, [offset for offset, _ in disk.reads])
        self.assertGreater(resumed.candidate_restore_bytes_read, 0)

    def test_raising_candidate_limit_resumes_after_saved_candidates_without_duplicates(self):
        disk = FakeDisk(size=8192)
        images = [jpeg(b"first"), jpeg(b"second"), jpeg(b"third")]
        offsets = (512, 2048, 4096)
        for offset, image in zip(offsets, images):
            disk.data[offset:offset + len(image)] = image

        first = RawContentCarver(disk, max_files=2).scan([(0, disk.size)])
        self.assertEqual([item.offset for item in first.files], list(offsets[:2]))
        self.assertTrue(first.file_count_limit_reached)

        resumed = RawContentCarver(disk, max_files=4).scan(
            [(0, disk.size)], resume_checkpoint=first.checkpoint,
        )

        self.assertEqual([item.offset for item in resumed.files], list(offsets))
        self.assertEqual(3, len({item.offset for item in resumed.files}))
        self.assertIsNone(resumed.checkpoint)

    def test_resume_profile_and_range_fingerprint_reject_stale_cursor(self):
        disk = FakeDisk(size=4096)
        first = RawContentCarver(disk, chunk_size=512, max_scan_bytes=1024).scan(
            [(0, disk.size)],
        )
        disk.reads.clear()

        restarted = RawContentCarver(disk, chunk_size=512, max_scan_bytes=1024).scan(
            [(512, disk.size)], resume_checkpoint=first.checkpoint,
        )

        self.assertEqual(disk.reads[0][0], 512)
        self.assertEqual(restarted.checkpoint.next_offset, 1536)

    def test_expanded_free_range_resumes_after_the_unchanged_processed_prefix(self):
        disk = FakeDisk(size=4096)
        first = RawContentCarver(disk, chunk_size=512, max_scan_bytes=1024).scan(
            [(0, 1024)], ranges_truncated=True,
        )
        checkpoint = first.checkpoint
        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint.next_offset, 1024)
        self.assertTrue(checkpoint.processed_range_fingerprint)

        disk.reads.clear()
        resumed = RawContentCarver(disk, chunk_size=512, max_scan_bytes=1024).scan(
            [(0, 4096)], resume_checkpoint=checkpoint,
        )

        self.assertEqual(disk.reads[0][0], 1024)
        self.assertEqual(resumed.checkpoint.next_offset, 2048)

    def test_expanded_ranges_reject_a_changed_processed_prefix(self):
        disk = FakeDisk(size=4096)
        first = RawContentCarver(disk, chunk_size=512, max_scan_bytes=1024).scan(
            [(0, 2048)],
        )
        disk.reads.clear()

        restarted = RawContentCarver(disk, chunk_size=512, max_scan_bytes=512).scan(
            [(512, 4096)], resume_checkpoint=first.checkpoint,
        )

        self.assertEqual(disk.reads[0][0], 512)
        self.assertEqual(restarted.checkpoint.next_offset, 1024)

    def test_raises_on_short_reads_instead_of_claiming_complete_scan(self):
        disk = FakeDisk(short_reads=True)

        with self.assertRaisesRegex(OSError, "Short content-carving read"):
            RawContentCarver(disk, chunk_size=512).scan([(0, 1024)])

    def test_rejects_ranges_outside_the_source_disk(self):
        disk = FakeDisk(size=512)

        with self.assertRaisesRegex(ValueError, "outside the physical disk"):
            RawContentCarver(disk).scan([(0, 513)])

    def test_does_not_retain_candidates_when_file_count_budget_is_zero(self):
        disk = FakeDisk()
        disk.data[100:100 + len(jpeg())] = jpeg()

        result = RawContentCarver(disk, max_files=0).scan([(0, 512)])

        self.assertEqual(result.files, ())
        self.assertEqual(result.bytes_scanned, 0)
        self.assertTrue(result.file_count_limit_reached)
        self.assertIsNotNone(result.checkpoint)

    def test_reports_retained_byte_limit_when_a_candidate_cannot_be_kept(self):
        disk = FakeDisk()
        disk.data[100:100 + len(jpeg())] = jpeg()

        result = RawContentCarver(
            disk, max_total_file_bytes=8,
        ).scan([(0, 512)])

        self.assertEqual(result.files, ())
        self.assertTrue(result.retained_bytes_limit_reached)

    def test_stops_at_file_count_limit_with_a_resumable_cursor(self):
        disk = FakeDisk(size=2048)
        candidate = jpeg()
        disk.data[100:100 + len(candidate)] = candidate
        disk.data[800:800 + len(candidate)] = candidate.replace(b"entropy-data", b"entropy-DATA")

        result = RawContentCarver(disk, max_files=1).scan([(0, disk.size)])

        self.assertEqual(len(result.files), 1)
        self.assertEqual(result.bytes_scanned, 103)
        self.assertFalse(result.scan_limit_reached)
        self.assertTrue(result.file_count_limit_reached)
        self.assertEqual(result.checkpoint.next_offset, 103)


if __name__ == "__main__":
    unittest.main()
