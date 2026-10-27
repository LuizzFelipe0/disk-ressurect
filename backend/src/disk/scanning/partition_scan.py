from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator


@dataclass(frozen=True)
class DiskChunk:
    offset: int
    data: bytes
    completed: int
    total: int
    region: str


@dataclass(frozen=True)
class DiskRange:
    name: str
    start: int
    end: int

    @property
    def size(self):
        return self.end - self.start


@dataclass(frozen=True)
class ScanCheckpoint:
    range_index: int
    next_offset: int
    disk_size: int
    bytes_per_sector: int


@dataclass(frozen=True)
class NTFSBootGeometry:
    bytes_per_sector: int
    cluster_size: int
    volume_size: int
    mft_lcn: int
    record_size: int


class DiskChunkSource:
    """Callable disk source that streams bounded ranges in sequential chunks."""

    def __init__(self, disk, chunk_size=64 * 1024 * 1024):
        self.disk = disk
        self.chunk_size = max(int(disk.bytes_per_sector), int(chunk_size))
        self.chunk_size -= self.chunk_size % int(disk.bytes_per_sector)

    def __call__(
        self,
        ranges: Iterable[DiskRange],
        progress_callback: Callable[[int, int, str], None] | None = None,
        checkpoint: ScanCheckpoint | None = None,
        checkpoint_callback: Callable[[ScanCheckpoint], None] | None = None,
        resume_overlap: int = 0,
    ) -> Iterator[DiskChunk]:
        ranges = tuple(region for region in ranges if region.size > 0)
        total = sum(region.size for region in ranges)
        sector_size = int(self.disk.bytes_per_sector)
        range_index = 0
        resume_offset = None
        if checkpoint is not None:
            if (checkpoint.disk_size != int(self.disk.size)
                    or checkpoint.bytes_per_sector != sector_size
                    or not 0 <= checkpoint.range_index < len(ranges)):
                raise ValueError("Scan checkpoint does not match this disk or scan")
            region = ranges[checkpoint.range_index]
            if not region.start <= checkpoint.next_offset <= region.end:
                raise ValueError("Scan checkpoint offset is outside its scan range")
            range_index = checkpoint.range_index
            resume_offset = max(region.start, checkpoint.next_offset - max(0, resume_overlap))
            resume_offset -= resume_offset % sector_size

        completed_before = sum(region.size for region in ranges[:range_index])
        if checkpoint_callback:
            checkpoint_callback(ScanCheckpoint(
                range_index=range_index,
                next_offset=resume_offset if resume_offset is not None else ranges[range_index].start,
                disk_size=int(self.disk.size),
                bytes_per_sector=sector_size,
            ))
        for current_index in range(range_index, len(ranges)):
            region = ranges[current_index]
            cursor = resume_offset if current_index == range_index and resume_offset is not None else region.start
            completed = completed_before + cursor - region.start
            while cursor < region.end:
                request = min(self.chunk_size, region.end - cursor)
                data = self.disk.read_at(cursor, request)
                if not data:
                    raise OSError(f"Read returned no data at disk offset {cursor:#x}")
                completed += len(data)
                if progress_callback:
                    progress_callback(
                        completed,
                        total,
                        f"{region.name} | {completed:,}/{total:,} bytes",
                    )
                yield DiskChunk(cursor, data, completed, total, region.name)
                cursor += len(data)
                if checkpoint_callback:
                    if cursor >= region.end and current_index + 1 < len(ranges):
                        next_index = current_index + 1
                        next_offset = ranges[next_index].start
                    else:
                        next_index = current_index
                        next_offset = min(cursor, region.end)
                    checkpoint_callback(ScanCheckpoint(
                        range_index=next_index,
                        next_offset=next_offset,
                        disk_size=int(self.disk.size),
                        bytes_per_sector=sector_size,
                    ))
            completed_before += region.size


class AlignedSignaturePipe:
    """Callable transformation from disk chunks to aligned signature offsets."""

    def __init__(self, signature: bytes, alignment: int, signature_offset: int = 0):
        if not signature:
            raise ValueError("Signature cannot be empty")
        if alignment <= 0:
            raise ValueError("Alignment must be positive")
        if signature_offset < 0:
            raise ValueError("Signature offset cannot be negative")
        self.signature = bytes(signature)
        self.alignment = int(alignment)
        self.signature_offset = int(signature_offset)

    def __call__(self, chunks: Iterable[DiskChunk]) -> Iterator[int]:
        carry = b""
        previous_end = None
        carry_size = len(self.signature) + self.signature_offset - 1
        for chunk in chunks:
            contiguous = previous_end == chunk.offset
            prefix = carry if contiguous else b""
            data = prefix + chunk.data
            base_offset = chunk.offset - len(prefix)
            position = 0
            while True:
                found = data.find(self.signature, position)
                if found < 0:
                    break
                position = found + 1
                candidate = base_offset + found - self.signature_offset
                if candidate >= 0 and candidate % self.alignment == 0:
                    yield candidate
            carry = data[-carry_size:] if carry_size else b""
            previous_end = chunk.offset + len(chunk.data)


class NTFSBootSectorParser:
    """Pure parser for NTFS boot-sector geometry and $MFT location metadata."""

    SIGNATURE = b"NTFS    "
    VALID_SECTOR_SIZES = {512, 1024, 2048, 4096}
    MAX_RECORD_SIZE = 65536

    @classmethod
    def parse(cls, boot_sector: bytes) -> NTFSBootGeometry | None:
        if len(boot_sector) < 512:
            return None
        if boot_sector[3:11] != cls.SIGNATURE or boot_sector[510:512] != b"\x55\xAA":
            return None
        try:
            bytes_per_sector = struct.unpack_from("<H", boot_sector, 11)[0]
            sectors_per_cluster = boot_sector[13]
            total_sectors = struct.unpack_from("<Q", boot_sector, 40)[0]
            mft_lcn = struct.unpack_from("<Q", boot_sector, 48)[0]
            record_code = struct.unpack_from("<b", boot_sector, 64)[0]
        except struct.error:
            return None
        if (bytes_per_sector not in cls.VALID_SECTOR_SIZES
                or sectors_per_cluster == 0
                or sectors_per_cluster & (sectors_per_cluster - 1)
                or total_sectors <= 0 or mft_lcn <= 0 or record_code == 0):
            return None
        cluster_size = bytes_per_sector * sectors_per_cluster
        record_size = cluster_size * record_code if record_code > 0 else 1 << (-record_code)
        volume_size = bytes_per_sector * total_sectors
        if (record_size < 512 or record_size > cls.MAX_RECORD_SIZE
                or record_size % 512 or mft_lcn * cluster_size >= volume_size):
            return None
        return NTFSBootGeometry(
            bytes_per_sector=bytes_per_sector,
            cluster_size=cluster_size,
            volume_size=volume_size,
            mft_lcn=mft_lcn,
            record_size=record_size,
        )
