import struct

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

        if self.raw_data[:4] == b"FILE" and self._apply_usa():
            self.is_valid = True
            self._parse()

    def _apply_usa(self):
        try:
            usa_off = struct.unpack("<H", self.raw_data[4:6])[0]
            usa_count = struct.unpack("<H", self.raw_data[6:8])[0]
            usa_seq = self.raw_data[usa_off:usa_off+2]
            for i in range(1, usa_count):
                sector_end = (i * 512) - 2
                if self.raw_data[sector_end:sector_end+2] == usa_seq:
                    self.raw_data[sector_end:sector_end+2] = self.raw_data[usa_off+(i*2) : usa_off+(i*2)+2]
            return True
        except: return False

    def _parse(self):
        attr_off = struct.unpack("<H", self.raw_data[20:22])[0]
        flags = struct.unpack("<H", self.raw_data[22:24])[0]

        # 0x01 = In Use. If 0, file is deleted. 0x02 = Directory.
        self.is_allocated = bool(flags & 0x01)
        self.is_dir = bool(flags & 0x02)

        curr = attr_off
        while curr < len(self.raw_data) - 8:
            atype = struct.unpack("<I", self.raw_data[curr:curr+4])[0]
            if atype == 0xFFFFFFFF: break
            alen = struct.unpack("<I", self.raw_data[curr+4:curr+8])[0]
            if alen <= 0: break

            if atype == 0x30: # $FILE_NAME
                c_off = struct.unpack("<H", self.raw_data[curr+20:curr+22])[0]
                fn = self.raw_data[curr+c_off:]
                self.parent_index = struct.unpack("<Q", fn[:8])[0] & 0xFFFFFFFFFFFF
                nlen = fn[64]
                try: self.name = fn[66:66+(nlen*2)].decode('utf-16le')
                except: self.name = f"Unknown_{self.index}"
            elif atype == 0x80: # $DATA
                self._parse_data(curr)
            curr += alen

    def _parse_data(self, curr):
        non_resident = self.raw_data[curr+8]
        if non_resident:
            self.file_size = struct.unpack("<Q", self.raw_data[curr+48:curr+56])[0]
            r_off = struct.unpack("<H", self.raw_data[curr+32:curr+34])[0]
            self.data_runs = self._parse_runlist(self.raw_data[curr+r_off : curr+struct.unpack("<I", self.raw_data[curr+4:curr+8])[0]])
        else:
            self.file_size = struct.unpack("<I", self.raw_data[curr+16:curr+20])[0]
            c_off = struct.unpack("<H", self.raw_data[curr+20:curr+22])[0]
            self.resident_data = self.raw_data[curr+c_off : curr+c_off+self.file_size]

    def _parse_runlist(self, data):
        runs = []; pos = 0; lcn = 0
        while pos < len(data) and data[pos] != 0:
            header = data[pos]; pos += 1
            l_sz = header & 0x0F; o_sz = (header >> 4) & 0x0F
            try:
                run_len = int.from_bytes(data[pos:pos+l_sz], 'little')
                pos += l_sz
                if o_sz > 0:
                    lcn += int.from_bytes(data[pos:pos+o_sz], 'little', signed=True)
                    runs.append((lcn, run_len))
                    pos += o_sz
                else: runs.append((None, run_len))
            except: break
        return runs