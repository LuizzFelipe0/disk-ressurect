import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from disk.deep_scan.primary_format_validators import (
    jpeg_header_status,
    png_decoded_size,
    valid_jpeg,
    valid_pdf,
)


def jpeg():
    return (
        b"\xff\xd8\xff\xe0\x00\x04\x00\x00"
        + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00payload\xff\xd9"
    )


def pdf():
    prefix = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    xref_offset = len(prefix)
    object_offset = len(b"%PDF-1.4\n")
    return (prefix + b"xref\n0 2\n0000000000 65535 f \n"
            + f"{object_offset:010d} 00000 n \n".encode("ascii")
            + b"trailer\n<< /Size 2 /Root 1 0 R >>\n"
            + b"startxref\n" + str(xref_offset).encode("ascii") + b"\n%%EOF\n")


class PrimaryFormatValidatorTests(unittest.TestCase):
    def test_jpeg_header_screen_distinguishes_incomplete_invalid_and_complete(self):
        candidate = jpeg()

        self.assertIsNone(jpeg_header_status(candidate[:4]))
        self.assertFalse(jpeg_header_status(b"not a jpeg"))
        self.assertTrue(jpeg_header_status(candidate[:candidate.index(b"\xff\xda") + 12]))

    def test_jpeg_validator_requires_frame_scan_and_end_marker(self):
        candidate = jpeg()

        self.assertTrue(valid_jpeg(candidate))
        self.assertFalse(valid_jpeg(candidate[:-2]))
        self.assertFalse(valid_jpeg(b"\xff\xd8" + b"payload" + b"\xff\xd9"))

    def test_png_decoded_size_accounts_for_scanline_filter_and_interlace(self):
        self.assertEqual(png_decoded_size(1, 1, 8, 6, 0), 5)
        self.assertEqual(png_decoded_size(1, 1, 8, 6, 1), 5)
        self.assertEqual(png_decoded_size(0, 1, 8, 6, 0), 1)

    def test_pdf_validator_requires_classic_xref_and_trailer_references(self):
        candidate = pdf()

        self.assertTrue(valid_pdf(candidate))
        self.assertFalse(valid_pdf(candidate.replace(b"xref\n", b"notxref\n", 1)))
        self.assertFalse(valid_pdf(candidate.replace(b"/Root 1 0 R", b"/Info 1 0 R")))


if __name__ == "__main__":
    unittest.main()
