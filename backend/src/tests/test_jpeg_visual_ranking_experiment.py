"""Test-only JPEG visual-ranking probe; ranking never resolves hypotheses."""

from __future__ import annotations

import hashlib
from io import BytesIO
import random
import sys
import unittest

from PIL import Image

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from test_jpeg_fragment_reconstruction_experiment import (
    ALIGNMENT,
    JpegEvidenceDiscovery,
    similar_jpeg_fixtures,
)


def _candidate_source(original: bytes, decoy: bytes):
    cut = ALIGNMENT
    data = bytearray(original[:cut])
    data.extend(b"F" * (ALIGNMENT * 2 - cut))
    first = len(data)
    data.extend(original[cut:])
    data.extend(b"G" * ((ALIGNMENT - len(data) % ALIGNMENT) % ALIGNMENT))
    second = len(data)
    data.extend(decoy[cut:])

    class Reader:
        def __init__(self, content):
            self.data = bytes(content)
            self.size = len(self.data)

        def read_at(self, offset, size):
            return self.data[offset:offset + size]

    return Reader(data), ((first - 1, first + 1), (second - 1, second + 1))


def _smoothness_score(candidate: bytes) -> int:
    """Global adjacent-pixel difference; a weak ranking signal, not validation."""
    with Image.open(BytesIO(candidate)) as source:
        image = source.convert("RGB")
        width, height = image.size
        pixels = image.tobytes()
    stride = width * 3
    horizontal = sum(
        abs(pixels[index] - pixels[index - 3])
        for y in range(height) for x in range(1, width)
        for index in (y * stride + x * 3, y * stride + x * 3 + 1, y * stride + x * 3 + 2)
    )
    vertical = sum(
        abs(pixels[index] - pixels[index - stride])
        for y in range(1, height) for x in range(width)
        for index in (y * stride + x * 3, y * stride + x * 3 + 1, y * stride + x * 3 + 2)
    )
    return horizontal + vertical


def _textured_original_and_smooth_decoy():
    width = height = 256
    original_pixels = bytearray()
    decoy_pixels = bytearray()
    rng = random.Random(203)
    for y in range(height):
        for x in range(width):
            shared = ((x * 17 + y * 13) % 256,
                      (x * 7 + y * 23) % 256,
                      (x * 29 + y * 3) % 256)
            if y < 200:
                original = decoy = shared
            else:
                original = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
                value = (y * 5) % 256
                decoy = (value, value, value)
            original_pixels.extend(original)
            decoy_pixels.extend(decoy)

    def encode(pixels):
        output = BytesIO()
        Image.frombytes("RGB", (width, height), bytes(pixels)).save(
            output, format="JPEG", quality=84, progressive=False,
            optimize=False, subsampling=0,
        )
        return output.getvalue()

    return encode(original_pixels), encode(decoy_pixels)


class JpegVisualRankingExperimentTests(unittest.TestCase):
    def _rank_two_hypotheses(self, original, decoy):
        source, ranges = _candidate_source(original, decoy)
        result = JpegEvidenceDiscovery(
            source, signature_offset=0, candidate_ranges=ranges,
        ).run()
        oracle_hash = hashlib.sha256(original).digest()
        ranked = sorted(
            (
                _smoothness_score(candidate),
                hashlib.sha256(candidate).digest() == oracle_hash,
            )
            for _cut, _location, candidate in result.hypotheses
        )
        return result, ranked

    def test_smoothness_ranks_original_first_on_similar_texture_fixtures(self):
        variants = (
            (False, 55, None),
            (False, 92, 4),
            (False, 84, None),
        )
        for progressive, quality, restart in variants:
            with self.subTest(progressive=progressive, quality=quality, restart=restart):
                original, decoy = similar_jpeg_fixtures(
                    progressive=progressive,
                    quality=quality,
                    restart_blocks=restart,
                )
                self.assertEqual(original[:ALIGNMENT], decoy[:ALIGNMENT])
                result, ranked = self._rank_two_hypotheses(original, decoy)
                self.assertEqual("ambiguous", result.stop_reason)
                self.assertEqual(2, len(ranked))
                self.assertTrue(ranked[0][1])

    def test_smoothness_can_rank_the_wrong_hypothesis_and_preserves_ambiguity(self):
        original, decoy = _textured_original_and_smooth_decoy()
        self.assertEqual(original[:ALIGNMENT], decoy[:ALIGNMENT])

        result, ranked = self._rank_two_hypotheses(original, decoy)

        self.assertEqual("ambiguous", result.stop_reason)
        self.assertEqual(2, len(ranked))
        self.assertFalse(ranked[0][1])
        self.assertEqual(1, sum(is_original for _score, is_original in ranked))


if __name__ == "__main__":
    unittest.main()
