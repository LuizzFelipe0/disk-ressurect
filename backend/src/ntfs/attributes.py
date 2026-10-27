import struct

class AttributeParser:
    @staticmethod
    def parse_runlist(data):
        """Decode a non-resident NTFS runlist, rejecting truncated encodings."""
        runs = []
        pos = 0
        lcn = 0
        terminated = False
        while pos < len(data):
            header = data[pos]
            pos += 1
            if header == 0:
                terminated = True
                break
            len_sz = header & 0x0F
            off_sz = (header >> 4) & 0x0F
            if len_sz == 0 or pos + len_sz + off_sz > len(data):
                raise ValueError("Malformed or truncated NTFS runlist")
            run_len = int.from_bytes(data[pos:pos+len_sz], 'little')
            pos += len_sz
            if run_len <= 0:
                raise ValueError("NTFS run length must be positive")
            if off_sz > 0:
                delta = int.from_bytes(data[pos:pos+off_sz], 'little', signed=True)
                pos += off_sz
                lcn += delta
                if lcn < 0:
                    raise ValueError("NTFS runlist references a negative cluster")
                runs.append((lcn, run_len))
            else:
                runs.append((None, run_len))
        if not terminated:
            raise ValueError("NTFS runlist is missing its terminator")
        return runs

    @staticmethod
    def get_file_name(content):
        """Decode a bounded $FILE_NAME value into its name and parent record."""
        if len(content) < 66:
            raise ValueError("Truncated $FILE_NAME value")
        name_len = content[64]
        name_end = 66 + name_len * 2
        if name_end > len(content):
            raise ValueError("Invalid $FILE_NAME length")
        parent_ref = struct.unpack_from("<Q", content, 0)[0] & 0xFFFFFFFFFFFF
        name = content[66:name_end].decode("utf-16le")
        return name, parent_ref
