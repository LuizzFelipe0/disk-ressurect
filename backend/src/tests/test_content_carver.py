import os
import sys
import unittest
import struct
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from disk.deep_scan.content_carver import RawContentCarver


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
        self.assertEqual(result.bytes_scanned, 512)
        self.assertEqual(result.candidate_bytes_read, len(candidate) - 1)
        self.assertEqual(result.files, ())

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
        self.assertGreater(result.bytes_scanned, 0)
        self.assertTrue(result.file_count_limit_reached)

    def test_reports_retained_byte_limit_when_a_candidate_cannot_be_kept(self):
        disk = FakeDisk()
        disk.data[100:100 + len(jpeg())] = jpeg()

        result = RawContentCarver(
            disk, max_total_file_bytes=8,
        ).scan([(0, 512)])

        self.assertEqual(result.files, ())
        self.assertTrue(result.retained_bytes_limit_reached)

    def test_reports_file_count_limit_even_when_range_scan_finishes(self):
        disk = FakeDisk(size=2048)
        candidate = jpeg()
        disk.data[100:100 + len(candidate)] = candidate
        disk.data[800:800 + len(candidate)] = candidate.replace(b"entropy-data", b"entropy-DATA")

        result = RawContentCarver(disk, max_files=1).scan([(0, disk.size)])

        self.assertEqual(len(result.files), 1)
        self.assertEqual(result.bytes_scanned, disk.size)
        self.assertFalse(result.scan_limit_reached)
        self.assertTrue(result.file_count_limit_reached)


if __name__ == "__main__":
    unittest.main()
