from infrastructure.disk.output_safety import OutputSafetyGuard
from infrastructure.formats.signature import FileSignatureValidator
from infrastructure.recovery.extractor import Extractor
from modules.recovery.service import RecoveryWorkflow
import struct


def make_recovery_workflow(output_guard=None, content_reader_factory=None):
    return RecoveryWorkflow(
        output_guard if output_guard is not None else OutputSafetyGuard(),
        content_reader_factory if content_reader_factory is not None else (lambda _source: None),
        FileSignatureValidator,
        Extractor,
    )


def resident_attribute(attribute_type, content, flags=0):
    length = (24 + len(content) + 7) & ~7
    attribute = bytearray(length)
    struct.pack_into("<II", attribute, 0, attribute_type, length)
    struct.pack_into("<H", attribute, 12, flags)
    attribute[8] = 0
    struct.pack_into("<I", attribute, 16, len(content))
    struct.pack_into("<H", attribute, 20, 24)
    attribute[24:24 + len(content)] = content
    return attribute


def make_record(name="photo.jpg", payload=b"data", has_attribute_list=False,
                record_number=0, base_file_reference=0, parent_reference=5,
                data_flags=0):
    raw = bytearray(1024)
    raw[:4] = b"FILE"
    struct.pack_into("<HH", raw, 4, 0x30, 3)
    raw[0x30:0x36] = b"\xAA\xBB\0\0\0\0"
    raw[510:512] = b"\xAA\xBB"
    raw[1022:1024] = b"\xAA\xBB"
    attribute_offset = 0x38
    struct.pack_into("<HH", raw, 20, attribute_offset, 1)
    struct.pack_into("<Q", raw, 32, base_file_reference)
    struct.pack_into("<I", raw, 44, record_number)

    encoded_name = name.encode("utf-16le")
    file_name = bytearray(66 + len(encoded_name))
    struct.pack_into("<Q", file_name, 0, parent_reference)
    file_name[64] = len(name)
    file_name[65] = 1
    file_name[66:] = encoded_name
    attributes = resident_attribute(0x30, file_name)
    if has_attribute_list:
        attributes += resident_attribute(0x20, b"\x00")
    attributes += resident_attribute(0x80, payload, data_flags)
    attributes += struct.pack("<I", 0xFFFFFFFF)
    attributes += bytes((-len(attributes)) % 8)
    raw[attribute_offset:attribute_offset + len(attributes)] = attributes
    struct.pack_into("<I", raw, 24, attribute_offset + len(attributes))
    return bytes(raw)
