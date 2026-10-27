import struct

from disk.models import PartitionEntry


class PartitionTableScanner:
    """Read MBR, extended MBR and GPT layouts from a physical disk."""

    MAX_GPT_ENTRIES = 4096
    MAX_EBR_ENTRIES = 128
    EXTENDED_MBR_TYPES = {0x05, 0x0F, 0x85}
    MBR_SECTOR_BYTES = 512

    def __init__(self, disk, sector_size=None):
        self.disk = disk
        self.sector_size = int(sector_size or disk.bytes_per_sector)
        if self.sector_size < self.MBR_SECTOR_BYTES:
            raise ValueError("Unsupported logical sector size")

    def partitions(self):
        mbr = self.disk.read_at(0, self.MBR_SECTOR_BYTES)
        if len(mbr) != self.MBR_SECTOR_BYTES or mbr[510:512] != b"\x55\xAA":
            return []
        entries = [self._mbr_entry(mbr, 446 + slot * 16, slot + 1) for slot in range(4)]
        if any(entry and entry.table_type == "GPT protective" for entry in entries):
            gpt = self._gpt_partitions()
            return gpt
        regular = [
            entry for entry in entries
            if entry and entry.table_type not in self.EXTENDED_MBR_TYPES
            and entry.offset < self.disk.size
            and entry.offset + entry.size_bytes <= self.disk.size
        ]
        extended = [entry for entry in entries if entry and entry.table_type in self.EXTENDED_MBR_TYPES]
        logical = []
        next_number = 5
        for container in extended:
            found = self._logical_partitions(container, next_number)
            logical.extend(found)
            next_number += len(found)
        result = regular + logical
        result = [
            entry for entry in result
            if entry.offset >= 0 and entry.size_bytes > 0
            and entry.offset + entry.size_bytes <= self.disk.size
        ]
        return sorted(result, key=lambda entry: (entry.offset, entry.number))

    def _mbr_entry(self, sector, offset, number):
        partition_type = sector[offset + 4]
        first_lba, sector_count = struct.unpack_from("<II", sector, offset + 8)
        if partition_type == 0 or sector_count == 0:
            return None
        name = f"MBR type 0x{partition_type:02X}"
        table_type = "GPT protective" if partition_type == 0xEE else partition_type
        return PartitionEntry(number, first_lba * self.sector_size,
                              sector_count * self.sector_size, table_type, name)

    def _logical_partitions(self, extended, first_number):
        base_lba = extended.offset // self.sector_size
        current_lba = base_lba
        result = []
        visited = set()
        for _ in range(self.MAX_EBR_ENTRIES):
            if current_lba in visited:
                break
            visited.add(current_lba)
            ebr = self.disk.read_at(current_lba * self.sector_size, self.MBR_SECTOR_BYTES)
            if len(ebr) != self.MBR_SECTOR_BYTES or ebr[510:512] != b"\x55\xAA":
                break
            data_entry = self._mbr_entry(ebr, 446, first_number + len(result))
            if data_entry and data_entry.table_type not in self.EXTENDED_MBR_TYPES:
                relative_lba, sector_count = struct.unpack_from("<II", ebr, 454)
                result.append(PartitionEntry(
                    first_number + len(result),
                    (current_lba + relative_lba) * self.sector_size,
                    sector_count * self.sector_size,
                    data_entry.table_type,
                    data_entry.name,
                ))
            link = self._mbr_entry(ebr, 462, 0)
            if link is None or link.table_type not in self.EXTENDED_MBR_TYPES:
                break
            relative_next = struct.unpack_from("<I", ebr, 470)[0]
            current_lba = base_lba + relative_next
        return result

    def _gpt_partitions(self):
        header = self.disk.read_at(self.sector_size, self.sector_size)
        if len(header) < 92 or header[:8] != b"EFI PART":
            return []
        header_size = struct.unpack_from("<I", header, 12)[0]
        if header_size < 92 or header_size > self.sector_size:
            return []
        entries_lba = struct.unpack_from("<Q", header, 72)[0]
        entry_count, entry_size = struct.unpack_from("<II", header, 80)
        if not 0 < entry_count <= self.MAX_GPT_ENTRIES or not 128 <= entry_size <= 4096:
            return []
        table_size = entry_count * entry_size
        table_offset = entries_lba * self.sector_size
        if table_offset > self.disk.size or table_size > self.disk.size - table_offset:
            return []
        table = self.disk.read_at(table_offset, table_size)
        if len(table) != table_size:
            return []
        result = []
        for index in range(entry_count):
            offset = index * entry_size
            entry = table[offset:offset + entry_size]
            if entry[:16] == bytes(16):
                continue
            first_lba, last_lba = struct.unpack_from("<QQ", entry, 32)
            if last_lba < first_lba:
                continue
            name = entry[56:min(entry_size, 128)].decode("utf-16le", errors="ignore").rstrip("\x00")
            partition = PartitionEntry(index + 1, first_lba * self.sector_size,
                                       (last_lba - first_lba + 1) * self.sector_size,
                                       "GPT", name)
            if partition.offset >= 0 and partition.size_bytes > 0 and partition.offset + partition.size_bytes <= self.disk.size:
                result.append(partition)
        return result
