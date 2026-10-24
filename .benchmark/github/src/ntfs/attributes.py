import struct

class AttributeParser:
    @staticmethod
    def parse_runlist(data):
        runs = []
        pos = 0
        lcn = 0
        while pos < len(data) and data[pos] != 0:
            header = data[pos]
            pos += 1
            len_sz = header & 0x0F
            off_sz = (header >> 4) & 0x0F
            run_len = int.from_bytes(data[pos:pos+len_sz], 'little')
            pos += len_sz
            if off_sz > 0:
                delta = int.from_bytes(data[pos:pos+off_sz], 'little', signed=True)
                pos += off_sz
                lcn += delta
                runs.append((lcn, run_len))
            else:
                runs.append((None, run_len))
        return runs

    @staticmethod
    def get_file_name(data, attr_content_offset):
        # Offset 64 do conteúdo do $FILE_NAME é o tamanho do nome
        content = data[attr_content_offset:]
        parent_ref = struct.unpack("<Q", content[:8])[0] & 0xFFFFFFFFFFFF
        name_len = content[64]
        try:
            name = content[66:66+(name_len*2)].decode('utf-16le')
        except: name = "UnknownName"
        return name, parent_ref