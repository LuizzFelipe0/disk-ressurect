"""Test-only probe of MP3 frame evidence; this is not a production validator."""

from __future__ import annotations

import hashlib
import random
import unittest


ID3V1_SIZE = 128
MAX_CANDIDATE_BYTES = 2 * 1024 * 1024


def _frame_header(bitrate_index=9, version_id=3, channel_mode=3, crc_present=False):
    protection_bit = 0 if crc_present else 1
    word = (
        (0x7FF << 21) | (version_id << 19) | (1 << 17) | (protection_bit << 16)
        | (bitrate_index << 12) | (channel_mode << 6)
    )
    return word.to_bytes(4, "big")


def _frame(bitrate_index=9, version_id=3, channel_mode=3, crc_present=False):
    header = _frame_header(bitrate_index, version_id, channel_mode, crc_present)
    mpeg1_bitrates = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
    size = 144 * mpeg1_bitrates[bitrate_index] * 1000 // 44_100
    return header + bytes(size - 4)


def _tagged_stream(frames):
    id3v2 = b"ID3\x03\x00\x00\x00\x00\x00\x00"
    id3v1 = b"TAG" + bytes(ID3V1_SIZE - 3)
    return id3v2 + b"".join(frames) + id3v1


def _probe_tagged_stream(data, start=0):
    """Return an exact ID3v2-to-ID3v1 boundary if headers form a frame chain."""
    if len(data) - start > MAX_CANDIDATE_BYTES or data[start:start + 3] != b"ID3":
        return None
    if len(data) < start + 10 or data[start + 3] not in (2, 3, 4):
        return None
    size_bytes = data[start + 6:start + 10]
    if len(size_bytes) != 4 or any(value & 0x80 for value in size_bytes):
        return None
    tag_size = 10 + sum(value << (7 * (3 - index)) for index, value in enumerate(size_bytes))
    cursor = start + tag_size
    first = None
    frame_count = 0
    previous_main_data_bytes = 0
    observed_bitrates = set()

    while cursor + 4 <= len(data):
        if data[cursor:cursor + 3] == b"TAG":
            end = cursor + ID3V1_SIZE
            if frame_count < 3 or end > len(data):
                return None
            return {
                "start": start,
                "end": end,
                "frame_count": frame_count,
                "variable_bitrate": len(observed_bitrates) > 1,
                "bytes_read": end - start,
            }

        word = int.from_bytes(data[cursor:cursor + 4], "big")
        if (word >> 21) & 0x7FF != 0x7FF:
            return None
        version_id = (word >> 19) & 0x03
        layer_id = (word >> 17) & 0x03
        bitrate_index = (word >> 12) & 0x0F
        sample_rate_index = (word >> 10) & 0x03
        if version_id == 1 or layer_id != 1 or bitrate_index in (0, 15) or sample_rate_index == 3:
            return None
        version = {3: 1, 2: 2, 0: 25}[version_id]
        base_rates = (44_100, 48_000, 32_000)
        divisor = {3: 1, 2: 2, 0: 4}[version_id]
        sample_rate = base_rates[sample_rate_index] // divisor
        bitrates = (
            (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
            if version == 1 else
            (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0)
        )
        bitrate = bitrates[bitrate_index]
        padding = (word >> 9) & 1
        frame_size = (144 if version == 1 else 72) * bitrate * 1000 // sample_rate + padding
        channel_mode = (word >> 6) & 0x03
        channels = 1 if channel_mode == 3 else 2
        if first is None:
            first = (version, sample_rate, channels)
        elif first != (version, sample_rate, channels):
            return None
        if cursor + frame_size > len(data):
            return None

        crc_present = ((word >> 16) & 1) == 0
        side_info_size = (17 if channels == 1 else 32) if version == 1 else (9 if channels == 1 else 17)
        side_info = cursor + 4 + (2 if crc_present else 0)
        if side_info + side_info_size > cursor + frame_size:
            return None
        main_data_begin = (
            (data[side_info] << 1) | (data[side_info + 1] >> 7)
            if version == 1 else data[side_info]
        )
        if main_data_begin > previous_main_data_bytes or (frame_count == 0 and main_data_begin != 0):
            return None
        previous_main_data_bytes += frame_size - 4 - (2 if crc_present else 0) - side_info_size
        frame_count += 1
        observed_bitrates.add(bitrate)
        cursor += frame_size


def _discover_tagged_streams(data):
    """Find candidates from ID3 signatures without fixture boundary inputs."""
    hypotheses = []
    cursor = 0
    while True:
        start = data.find(b"ID3", cursor)
        if start < 0:
            return hypotheses
        candidate = _probe_tagged_stream(data, start)
        if candidate is not None:
            hypotheses.append(candidate)
        cursor = start + 3


class MP3ContiguousEvidenceExperimentTests(unittest.TestCase):
    def test_tagged_frame_sequence_is_a_bounded_structural_hypothesis_only(self):
        candidate = _tagged_stream((_frame(9), _frame(8), _frame(9)))

        hypotheses = _discover_tagged_streams(candidate)

        self.assertEqual(1, len(hypotheses))
        hypothesis = hypotheses[0]
        self.assertEqual(3, hypothesis["frame_count"])
        self.assertTrue(hypothesis["variable_bitrate"])
        self.assertEqual(len(candidate), hypothesis["bytes_read"])
        # The oracle is evaluated after the probe and cannot select the frames.
        recovered_candidate = candidate[hypothesis["start"]:hypothesis["end"]]
        self.assertEqual(hashlib.sha256(candidate).digest(), hashlib.sha256(recovered_candidate).digest())
        self.assertNotIn("decoded", hypothesis)

    def test_random_data_and_an_isolated_sync_marker_are_rejected(self):
        rng = random.Random(0x3E)
        noise = bytearray(rng.randbytes(4096))
        marker = _frame_header()
        noise[1024:1024 + len(marker)] = marker

        self.assertEqual([], _discover_tagged_streams(bytes(noise)))

    def test_incompatible_frames_and_truncated_final_frames_are_rejected(self):
        incompatible = _tagged_stream((_frame(), _frame(version_id=2), _frame()))
        channel_mismatch = _tagged_stream((_frame(), _frame(channel_mode=0), _frame()))
        truncated = _tagged_stream((_frame(), _frame(), _frame()[:-1]))

        self.assertEqual([], _discover_tagged_streams(incompatible))
        self.assertEqual([], _discover_tagged_streams(channel_mismatch))
        self.assertEqual([], _discover_tagged_streams(truncated))

    def test_crc_protected_header_with_corrupt_crc_bytes_still_passes_the_probe(self):
        frames = [_frame(crc_present=True) for _ in range(3)]
        frames[1] = frames[1][:4] + b"\x12\x34" + frames[1][6:]

        # CRC bytes are present but deliberately not checked by this probe.
        self.assertEqual(1, len(_discover_tagged_streams(_tagged_stream(frames))))

    def test_concatenated_tagged_streams_have_two_boundaries_not_one_order_proof(self):
        first = _tagged_stream((_frame(), _frame(), _frame()))
        second = _tagged_stream((_frame(8), _frame(9), _frame(8)))
        source = first + second

        hypotheses = _discover_tagged_streams(source)

        self.assertEqual(2, len(hypotheses))
        first_hypothesis, second_hypothesis = hypotheses
        self.assertEqual(len(first), first_hypothesis["end"])
        self.assertEqual((len(first), len(source)),
                         (second_hypothesis["start"], second_hypothesis["end"]))
        # Both digests are test-oracle checks after boundary hypotheses exist.
        self.assertEqual(
            hashlib.sha256(first).digest(),
            hashlib.sha256(source[first_hypothesis["start"]:first_hypothesis["end"]]).digest(),
        )
        self.assertEqual(
            hashlib.sha256(second).digest(),
            hashlib.sha256(source[second_hypothesis["start"]:second_hypothesis["end"]]).digest(),
        )

    def test_candidate_size_limit_is_independent_of_frame_count(self):
        oversized = b"ID3" + bytes(MAX_CANDIDATE_BYTES)

        self.assertEqual([], _discover_tagged_streams(oversized))


if __name__ == "__main__":
    unittest.main()
