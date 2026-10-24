import struct

from ntfs.attributes import AttributeParser

class MFTRecord:
    """Parses a single NTFS MFT Record."""
    def __init__(self, data, index, disk=None, mft_offset=None):
        self.raw_data = bytearray(data)
        self.index = index
        self.disk = disk
        self.mft_offset = mft_offset
        self.is_valid = False
        self.is_allocated = False # Tells if file was deleted (Recycle Bin/Format)
        self.is_dir = False
        self.name = ""
        self.parent_index = None
        self.data_runs = []
        self.file_size = 0
        self.resident_data = None
        self.data_is_complete = True
        self._filename_priority = -1

        if len(self.raw_data) != 1024 or self.raw_data[:4] != b"FILE":
            return
        try:
            if not self._apply_usa():
                return
            self._parse()
            self.is_valid = True
        except (IndexError, struct.error, ValueError, OverflowError):
            self.is_valid = False

    def _apply_usa(self):
        usa_off, usa_count = struct.unpack_from("<HH", self.raw_data, 4)
        sectors = len(self.raw_data) // 512
        if usa_count != sectors + 1 or usa_off < 8 or usa_off + usa_count * 2 > len(self.raw_data):
            return False
        usa_seq = bytes(self.raw_data[usa_off:usa_off + 2])
        for i in range(1, usa_count):
            sector_end = i * 512 - 2
            if self.raw_data[sector_end:sector_end + 2] != usa_seq:
                return False
        for i in range(1, usa_count):
            sector_end = i * 512 - 2
            replacement = usa_off + i * 2
            self.raw_data[sector_end:sector_end + 2] = self.raw_data[replacement:replacement + 2]
        return True

    def _parse(self):
        attr_off = struct.unpack_from("<H", self.raw_data, 20)[0]
        flags = struct.unpack_from("<H", self.raw_data, 22)[0]
        bytes_in_use = struct.unpack_from("<I", self.raw_data, 24)[0]
        if attr_off < 24 or bytes_in_use > len(self.raw_data) or attr_off >= bytes_in_use:
            raise ValueError("Invalid MFT attribute bounds")
        
        # 0x01 = In Use. If 0, file is deleted. 0x02 = Directory.
        self.is_allocated = bool(flags & 0x01)
        self.is_dir = bool(flags & 0x02)
        
        curr = attr_off
        data_attributes = 0
        terminated = False
        while curr + 4 <= bytes_in_use:
            atype = struct.unpack_from("<I", self.raw_data, curr)[0]
            if atype == 0xFFFFFFFF:
                terminated = True
                break
            if curr + 8 > bytes_in_use:
                raise ValueError("Truncated MFT attribute header")
            alen = struct.unpack_from("<I", self.raw_data, curr + 4)[0]
            if alen < 16 or curr + alen > bytes_in_use:
                raise ValueError("Invalid MFT attribute length")

            if atype == 0x30: # $FILE_NAME
                self._parse_file_name(curr, alen)
            elif atype == 0x20: # $ATTRIBUTE_LIST may point to additional data extents.
                self.data_is_complete = False
            elif atype == 0x80: # $DATA
                name_length = self.raw_data[curr + 9]
                if name_length == 0:
                    data_attributes += 1
                    if data_attributes > 1:
                        self.data_is_complete = False
                    self._parse_data(curr, alen)
            curr += alen
        if not terminated:
            raise ValueError("MFT record has no attribute terminator")

    def _parse_file_name(self, curr, attr_len):
        if attr_len < 0x18:
            raise ValueError("Truncated $FILE_NAME attribute")
        content_offset = struct.unpack_from("<H", self.raw_data, curr + 20)[0]
        content_length = struct.unpack_from("<I", self.raw_data, curr + 16)[0]
        start = curr + content_offset
        end = start + content_length
        if content_offset < 24 or end > curr + attr_len or content_length < 66:
            raise ValueError("Invalid $FILE_NAME content bounds")
        content = self.raw_data[start:end]
        name, parent_index = AttributeParser.get_file_name(content)
        namespace = content[65]
        priority = {0: 2, 1: 3, 2: 1, 3: 3}.get(namespace, 0)
        if priority >= self._filename_priority:
            self.parent_index = parent_index
            self.name = name
            self._filename_priority = priority

    def _parse_data(self, curr, attr_len):
        non_resident = self.raw_data[curr+8]
        if non_resident:
            if attr_len < 64:
                raise ValueError("Truncated non-resident $DATA attribute")
            lowest_vcn = struct.unpack_from("<Q", self.raw_data, curr + 16)[0]
            if lowest_vcn != 0:
                self.data_is_complete = False
            self.file_size = struct.unpack_from("<Q", self.raw_data, curr + 48)[0]
            runlist_offset = struct.unpack_from("<H", self.raw_data, curr + 32)[0]
            if runlist_offset < 64 or runlist_offset >= attr_len:
                raise ValueError("Invalid $DATA runlist offset")
            self.data_runs = AttributeParser.parse_runlist(
                self.raw_data[curr + runlist_offset:curr + attr_len]
            )
        else:
            if attr_len < 24:
                raise ValueError("Truncated resident $DATA attribute")
            self.file_size = struct.unpack_from("<I", self.raw_data, curr + 16)[0]
            content_offset = struct.unpack_from("<H", self.raw_data, curr + 20)[0]
            if content_offset < 24 or content_offset + self.file_size > attr_len:
                raise ValueError("Invalid resident $DATA content bounds")
            self.resident_data = bytes(
                self.raw_data[curr + content_offset:curr + content_offset + self.file_size]
            )
