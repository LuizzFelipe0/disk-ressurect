"""Build deterministic benchmark inputs; oracle records stay separate from readers."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import random
from pathlib import Path
import zlib

from PIL import Image

from infrastructure.filesystems.ntfs.allocation.cluster_allocation import FreeClusterRangeCollector
from .ground_truth import GroundTruthEntry, GroundTruthManifest


CLUSTER_SIZE = 4096
MAX_DATASET_BYTES = 256 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class BuiltDataset:
    path: Path
    manifest: GroundTruthManifest
    ntfs_runs: tuple[tuple[int | None, int], ...]
    partial_png_offset: int
    partial_png_original_pixels: bytes


def _image_bytes(seed, *, format_name, quality=88, progressive=False):
    rng = random.Random(seed)
    width, height = (32, 16) if format_name == "PNG" else (192, 128)
    pixels = rng.randbytes(width * height * 3)
    image = Image.frombytes("RGB", (width, height), pixels)
    output = BytesIO()
    if format_name == "JPEG":
        image.save(output, format="JPEG", quality=quality, progressive=progressive,
                   optimize=False, subsampling=0)
    else:
        image.save(output, format="PNG", compress_level=3)
    encoded = output.getvalue()
    with Image.open(BytesIO(encoded)) as decoded:
        decoded.load()
        if decoded.format != format_name or decoded.size != (width, height):
            raise AssertionError("Generated media fixture did not decode as expected")
    return encoded, pixels, (width, height)


def _partial_png(seed):
    original, pixels, (width, height) = _image_bytes(seed, format_name="PNG")
    cursor = len(PNG_SIGNATURE)
    while cursor + 12 <= len(original):
        length = int.from_bytes(original[cursor:cursor + 4], "big")
        kind = original[cursor + 4:cursor + 8]
        payload_start = cursor + 8
        if kind == b"IDAT":
            cut = payload_start + max(16, length * 3 // 4)
            return original[:cut], original, pixels, width, height
        cursor += length + 12
    raise AssertionError("Generated PNG has no IDAT chunk")


def _free_ranges(size_bytes, allocated_clusters):
    cluster_count = size_bytes // CLUSTER_SIZE
    bitmap = bytearray((cluster_count + 7) // 8)
    for cluster in allocated_clusters:
        bitmap[cluster // 8] |= 1 << (cluster % 8)
    collector = FreeClusterRangeCollector(0, CLUSTER_SIZE, cluster_count)
    collector.consume(bitmap, 0)
    return collector.finish()["ranges"]


def create_dataset(path, size_bytes, *, seed=72531):
    path = Path(path)
    size_bytes = int(size_bytes)
    if (size_bytes <= 8 * 1024 * 1024 or size_bytes > MAX_DATASET_BYTES
            or size_bytes % CLUSTER_SIZE):
        raise ValueError("Dataset size must be cluster aligned and between 8 and 256 MiB")
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    with path.open("wb") as output:
        remaining = size_bytes
        while remaining:
            block = rng.randbytes(min(1024 * 1024, remaining))
            output.write(block)
            remaining -= len(block)

    entries = []
    with path.open("r+b") as image_file:
        def put(offset, data):
            image_file.seek(offset)
            image_file.write(data)

        jpeg_contiguous, _pixels, _geometry = _image_bytes(
            seed + 1, format_name="JPEG", quality=88,
        )
        jpeg_progressive, _pixels, _geometry = _image_bytes(
            seed + 2, format_name="JPEG", quality=72, progressive=True,
        )
        png_contiguous, _pixels, _geometry = _image_bytes(seed + 3, format_name="PNG")
        partial_bytes, partial_original, partial_pixels, width, height = _partial_png(seed + 4)

        contig_offset = 1024 * 1024
        duplicate_offset = 2 * 1024 * 1024
        png_offset = 3 * 1024 * 1024
        progressive_offset = 4 * 1024 * 1024
        overwrite_offset = 5 * 1024 * 1024
        metadata_first = 8 * 1024 * 1024
        metadata_second = 12 * 1024 * 1024
        untracked_first = 16 * 1024 * 1024
        untracked_second = 20 * 1024 * 1024
        partial_offset = 24 * 1024 * 1024
        false_signature_offset = 30 * 1024 * 1024

        put(contig_offset, jpeg_contiguous)
        put(duplicate_offset, jpeg_contiguous)
        put(png_offset, png_contiguous)
        put(progressive_offset, jpeg_progressive)
        damaged = bytearray(jpeg_contiguous)
        damaged[len(damaged) // 2] ^= 0x7F
        put(overwrite_offset, damaged)
        split = CLUSTER_SIZE
        put(metadata_first, jpeg_contiguous[:split])
        put(metadata_second, jpeg_contiguous[split:])
        unknown_split = max(512, len(jpeg_progressive) // 2)
        put(untracked_first, jpeg_progressive[:unknown_split])
        put(untracked_second, jpeg_progressive[unknown_split:])
        put(partial_offset, partial_bytes)
        partial_cluster_end = partial_offset + CLUSTER_SIZE
        put(partial_offset + len(partial_bytes), b"\xa5" * (partial_cluster_end - partial_offset - len(partial_bytes)))
        put(false_signature_offset, b"\xff\xd8\xff" + b"not-a-jpeg" * 8)

    metadata_first_cluster = metadata_first // CLUSTER_SIZE
    metadata_second_cluster = metadata_second // CLUSTER_SIZE
    metadata_second_clusters = (len(jpeg_contiguous) - CLUSTER_SIZE + CLUSTER_SIZE - 1) // CLUSTER_SIZE
    ntfs_runs = ((metadata_first_cluster, 1), (metadata_second_cluster, metadata_second_clusters))
    allocated_clusters = {metadata_first_cluster}
    allocated_clusters.update(range(metadata_second_cluster,
                                    metadata_second_cluster + metadata_second_clusters))
    # A synthetic allocated cluster immediately after the damaged PNG bounds the eligible range.
    allocated_clusters.add(partial_offset // CLUSTER_SIZE + 1)
    eligible_ranges = _free_ranges(size_bytes, allocated_clusters)
    excluded_ranges = tuple(
        (cluster * CLUSTER_SIZE, (cluster + 1) * CLUSTER_SIZE)
        for cluster in sorted(allocated_clusters)
    )
    entries.extend((
        GroundTruthEntry.original("contiguous-jpeg", jpeg_contiguous,
                                  physical_ranges=((contig_offset, contig_offset + len(jpeg_contiguous)),)),
        GroundTruthEntry.original("duplicate-jpeg-copy", jpeg_contiguous,
                                  physical_ranges=((duplicate_offset, duplicate_offset + len(jpeg_contiguous)),)),
        GroundTruthEntry.original("contiguous-png", png_contiguous,
                                  physical_ranges=((png_offset, png_offset + len(png_contiguous)),)),
        GroundTruthEntry.original("progressive-jpeg", jpeg_progressive,
                                  physical_ranges=((progressive_offset, progressive_offset + len(jpeg_progressive)),)),
        GroundTruthEntry.original("metadata-fragmented-jpeg", jpeg_contiguous,
                                  physical_ranges=((metadata_first, metadata_first + CLUSTER_SIZE),
                                                   (metadata_second, metadata_second + len(jpeg_contiguous) - CLUSTER_SIZE)),
                                  fragmentation="two-run", allocation_evidence="synthetic_allocated_bitmap",
                                  expected_recovery="ntfs_runlist_component"),
        GroundTruthEntry.original("fragmented-jpeg-no-metadata", jpeg_progressive,
                                  physical_ranges=((untracked_first, untracked_first + unknown_split),
                                                   (untracked_second, untracked_second + len(jpeg_progressive) - unknown_split)),
                                  fragmentation="two-fragment", expected_recovery="miss_without_metadata"),
        GroundTruthEntry.original("partially-overwritten-jpeg", jpeg_contiguous,
                                  physical_ranges=((overwrite_offset, overwrite_offset + len(damaged)),),
                                  corruption_regions=((overwrite_offset + len(damaged) // 2,
                                                       overwrite_offset + len(damaged) // 2 + 1),),
                                  expected_recovery="reject_or_inconclusive", negative_reason="middle byte overwritten"),
        GroundTruthEntry.original("partial-png", partial_original,
                                  physical_ranges=((partial_offset, partial_offset + len(partial_bytes)),),
                                  expected_recovery="partial_png_rows_only"),
        GroundTruthEntry.original("fully-overwritten-negative", b"original-content-absent",
                                  fragmentation="overwritten", allocation_evidence="not_present",
                                  expected_recovery="no_candidate", negative_reason="original bytes are not in the source"),
    ))
    manifest = GroundTruthManifest(
        seed=int(seed), workload=f"file-backed-{size_bytes // (1024 * 1024)}MiB-v1",
        size_bytes=size_bytes, entries=tuple(entries), eligible_ranges=eligible_ranges,
        excluded_ranges=excluded_ranges,
        overwrite_regions=((overwrite_offset + len(damaged) // 2,
                            overwrite_offset + len(damaged) // 2 + 1),),
    )
    return BuiltDataset(path, manifest, ntfs_runs, partial_offset, partial_pixels)
