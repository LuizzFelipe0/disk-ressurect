from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable, Iterator

from disk.scanning.partition_scan import DiskChunk, DiskChunkSource, DiskRange
from ntfs.mft_parser import MFTRecord


@dataclass(frozen=True)
class MFTAnchor:
    physical_offset: int
    record: MFTRecord


class MFTRecordAnchorPipe:
    """Transform disk chunks into validated $MFT root-record anchors."""

    SIGNATURE = b"FILE"
    MAX_RECORD_SIZE = 65536

    def __call__(self, chunks: Iterable[DiskChunk]) -> Iterator[MFTAnchor]:
        carry = b""
        previous_end = None
        yielded_offsets = set()
        for chunk in chunks:
            prefix = carry if previous_end == chunk.offset else b""
            data = prefix + chunk.data
            base_offset = chunk.offset - len(prefix)
            position = 0
            while True:
                found = data.find(self.SIGNATURE, position)
                if found < 0:
                    break
                position = found + len(self.SIGNATURE)
                physical_offset = base_offset + found
                if physical_offset % 512 or physical_offset in yielded_offsets:
                    continue
                if found + 8 > len(data):
                    continue
                usa_count = struct.unpack_from("<H", data, found + 6)[0]
                record_size = (usa_count - 1) * 512
                if not 512 <= record_size <= self.MAX_RECORD_SIZE:
                    continue
                end = found + record_size
                if end > len(data):
                    continue
                record_data = data[found:end]
                record = MFTRecord(
                    record_data,
                    physical_offset // record_size,
                    mft_offset=physical_offset,
                    record_size=record_size,
                )
                if (record.is_valid and record.name == "$MFT"
                        and record.data_runs and record.file_size > 0
                        and record.allocated_size > 0 and record.data_is_complete):
                    yielded_offsets.add(physical_offset)
                    yield MFTAnchor(physical_offset, record)
            carry_size = self.MAX_RECORD_SIZE - 1
            carry = data[-carry_size:]
            previous_end = chunk.offset + len(chunk.data)


class MFTAnchorScanner:
    """Scan a bounded disk prefix for a trustworthy $MFT root record."""

    DEFAULT_SCAN_LIMIT = 8 * 1024 * 1024 * 1024
    DEFAULT_CHUNK_SIZE = 64 * 1024 * 1024

    def __init__(self, disk, scan_limit=DEFAULT_SCAN_LIMIT, chunk_size=DEFAULT_CHUNK_SIZE):
        self.disk = disk
        self.scan_limit = max(0, int(scan_limit))
        self.chunk_source = DiskChunkSource(disk, chunk_size)
        self.anchor_pipe = MFTRecordAnchorPipe()

    def scan(self, progress_callback=None):
        end = min(self.scan_limit, int(self.disk.size))
        if end == 0:
            return None
        chunks = self.chunk_source(
            [DiskRange("MFT anchor search", 0, end)],
            progress_callback,
        )
        return next(self.anchor_pipe(chunks), None)
