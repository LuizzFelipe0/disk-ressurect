"""Test-only evidence about ISO-BMFF logical offsets and physical fragments."""

from __future__ import annotations

import hashlib
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from infrastructure.carving.content_carver import RawContentCarver
from infrastructure.formats.additional import validate_additional_candidate


def _box(kind, payload):
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def _movie(sample_data):
    ftyp = _box(b"ftyp", b"isom\x00\x00\x00\x00isom")
    stsz = _box(b"stsz", b"\x00" * 4 + struct.pack(">II", len(sample_data), 1))
    stco_payload = b"\x00" * 4 + struct.pack(">II", 1, 0)
    stco = _box(b"stco", stco_payload)
    stbl = _box(b"stbl", stsz + stco)
    moov = _box(b"moov", _box(b"trak", _box(b"mdia", _box(b"minf", stbl))))
    sample_offset = len(ftyp) + len(moov) + 8
    stco_payload = b"\x00" * 4 + struct.pack(">II", 1, sample_offset)
    stco = _box(b"stco", stco_payload)
    moov = _box(b"moov", _box(b"trak", _box(b"mdia", _box(b"minf", _box(b"stbl", stsz + stco)))))
    return ftyp + moov + _box(b"mdat", sample_data), sample_offset


class _MemoryDisk:
    def __init__(self, data):
        self.data = bytes(data)
        self.size = len(self.data)
        self.bytes_read = 0

    def read_at(self, offset, size):
        chunk = self.data[offset:offset + size]
        self.bytes_read += len(chunk)
        return chunk


class IsoBmffFragmentEvidenceExperimentTests(unittest.TestCase):
    def test_stco_points_into_logical_file_not_to_the_physical_continuation(self):
        sample = bytes(range(128))
        original, logical_sample_offset = _movie(sample)
        split_at = logical_sample_offset + 32
        prefix, continuation = original[:split_at], original[split_at:]
        foreign = b"foreign-data!!"
        image = prefix + foreign + continuation
        physical_continuation_offset = len(prefix) + len(foreign)

        self.assertEqual(sample[:8], original[logical_sample_offset:logical_sample_offset + 8])
        self.assertNotEqual(logical_sample_offset + 32, physical_continuation_offset)
        self.assertEqual(foreign[:8], image[logical_sample_offset + 32:logical_sample_offset + 40])
        self.assertNotEqual(original, image[:len(original)])

    def test_existing_contiguous_carver_accepts_foreign_bytes_inside_mdat_as_false_positive(self):
        sample = bytes(range(128))
        original, logical_sample_offset = _movie(sample)
        split_at = logical_sample_offset + 32
        prefix, continuation = original[:split_at], original[split_at:]
        source = prefix + b"foreign-data!!" + continuation
        disk = _MemoryDisk(source)

        result = RawContentCarver(disk).scan(((0, len(source)),))

        candidates = [item for item in result.files if item.extension == ".mp4"]
        self.assertEqual(1, len(candidates))
        stats = {item.extension: item for item in result.format_stats}
        self.assertEqual(1, stats[".mp4"].candidates_examined)
        self.assertEqual(len(original), stats[".mp4"].candidate_bytes_read)
        self.assertEqual(len(source) + len(original), disk.bytes_read)
        self.assertEqual(len(source), result.bytes_scanned)
        self.assertNotEqual(hashlib.sha256(original).digest(),
                            hashlib.sha256(candidates[0].data).digest())
        self.assertEqual(len(original), len(candidates[0].data))

    def test_same_declared_mdat_shape_cannot_disambiguate_correct_and_decoy_payloads(self):
        sample = bytes(range(128))
        original, _logical_sample_offset = _movie(sample)
        structural_hypotheses = (
            original,
            _movie(bytes(reversed(sample)))[0],
        )

        accepted = [validate_additional_candidate(item) for item in structural_hypotheses]

        self.assertEqual([".mp4", ".mp4"], [item.extension for item in accepted if item])
        self.assertEqual(1, sum(
            hashlib.sha256(item).digest() == hashlib.sha256(original).digest()
            for item in structural_hypotheses
        ))
        # The structural validator does not inspect stco/stsz or decode samples.

    def test_missing_or_invalid_sample_offsets_are_invisible_to_top_level_validator(self):
        sample = bytes(range(32))
        ftyp = _box(b"ftyp", b"isom\x00\x00\x00\x00isom")
        no_sample_table = ftyp + _box(b"moov", b"") + _box(b"mdat", sample)
        original, _sample_offset = _movie(sample)
        invalid_offset = bytearray(original)
        stco_type = invalid_offset.index(b"stco")
        invalid_offset[stco_type + 12:stco_type + 16] = b"\xff" * 4

        self.assertEqual(".mp4", validate_additional_candidate(no_sample_table).extension)
        self.assertEqual(".mp4", validate_additional_candidate(bytes(invalid_offset)).extension)

    def test_partial_sample_overwrite_stays_top_level_valid_but_fails_oracle_hash(self):
        sample = bytes(range(128))
        original, sample_offset = _movie(sample)
        overwritten = bytearray(original)
        overwritten[sample_offset + 24:sample_offset + 32] = b"OVERWRIT"

        self.assertEqual(".mp4", validate_additional_candidate(bytes(overwritten)).extension)
        self.assertNotEqual(hashlib.sha256(original).digest(),
                            hashlib.sha256(overwritten).digest())

    def test_physically_reordered_fragments_are_not_recovered_by_contiguous_carver(self):
        sample = bytes(range(128))
        original, sample_offset = _movie(sample)
        split_at = sample_offset + 32
        prefix, continuation = original[:split_at], original[split_at:]
        reordered = continuation + b"foreign-data!!" + prefix
        disk = _MemoryDisk(reordered)

        result = RawContentCarver(disk).scan(((0, len(reordered)),))

        self.assertEqual((), result.files)
        stats = {item.extension: item for item in result.format_stats}
        self.assertEqual(0, stats[".mp4"].files_found)

    def test_moof_is_a_container_fragment_not_physical_fragment_evidence(self):
        candidate = (
            _box(b"ftyp", b"isom\x00\x00\x00\x00isom")
            + _box(b"moof", b"synthetic fragment metadata")
            + _box(b"mdat", b"sample bytes")
        )

        result = validate_additional_candidate(candidate)

        self.assertIsNotNone(result)
        self.assertEqual(".mp4", result.extension)


if __name__ == "__main__":
    unittest.main()
