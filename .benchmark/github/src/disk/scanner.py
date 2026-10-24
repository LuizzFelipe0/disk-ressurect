import struct
from collections import Counter
from ntfs.mft_parser import MFTRecord

class DiskScanner:
    """Discovers partition offsets (VOL_START) using various techniques."""
    def __init__(self, disk, cluster_size=4096):
        self.disk = disk
        self.cluster_size = cluster_size

    def discover_via_mft_record(self, mft_phys):
        """Calculates VOL_START by reading the $MFT runlist."""
        print(f"[*] [Scanner] Analyzing $MFT at {hex(mft_phys)}...")
        raw = self.disk.read_at(mft_phys, 1024)
        if raw[:4] != b"FILE": return None

        attr_off = struct.unpack("<H", raw[20:22])[0]
        pos = attr_off
        while pos < len(raw) - 8:
            atype = struct.unpack("<I", raw[pos:pos+4])[0]
            if atype == 0xFFFFFFFF: break
            alen = struct.unpack("<I", raw[pos+4:pos+8])[0]

            if atype == 0x80: # $DATA
                run_off = struct.unpack("<H", raw[pos+32:pos+34])[0]
                run_data = raw[pos+run_off : pos+alen]
                header = run_data[0]
                len_sz = header & 0x0F
                off_sz = (header >> 4) & 0x0F
                if off_sz > 0:
                    mft_lcn = int.from_bytes(run_data[1+len_sz : 1+len_sz+off_sz], 'little', signed=True)
                    return mft_phys - (mft_lcn * self.cluster_size)
            pos += alen
        return None