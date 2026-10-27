import zlib
import zipfile


class FileSignatureValidator:
    ZIP_SIGNATURE = b"PK\x03\x04"
    OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
    PDF_HEADER_WINDOW = 1024
    ZIP_DOCUMENT_MEMBERS = {
        ".docx": "word/document.xml",
        ".docm": "word/document.xml",
        ".xlsx": "xl/workbook.xml",
        ".xlsm": "xl/workbook.xml",
    }
    SIGNATURES = {
        ".jpg": ((0, b"\xFF\xD8\xFF"),),
        ".jpeg": ((0, b"\xFF\xD8\xFF"),),
        ".png": ((0, b"\x89PNG\r\n\x1a\n"),),
        ".pdf": ((0, b"%PDF-"),),
        ".doc": ((0, OLE_SIGNATURE),),
        ".xls": ((0, OLE_SIGNATURE),),
        ".docx": ((0, ZIP_SIGNATURE), (0, OLE_SIGNATURE)),
        ".docm": ((0, ZIP_SIGNATURE), (0, OLE_SIGNATURE)),
        ".xlsx": ((0, ZIP_SIGNATURE), (0, OLE_SIGNATURE)),
        ".xlsm": ((0, ZIP_SIGNATURE), (0, OLE_SIGNATURE)),
        ".rtf": ((0, b"{\\rtf"),),
        ".mp4": ((4, b"ftyp"),),
    }

    @classmethod
    def supported_extensions(cls):
        return tuple(sorted(cls.SIGNATURES))

    @classmethod
    def header_window(cls, extension):
        return cls.PDF_HEADER_WINDOW if extension == ".pdf" else 8

    @classmethod
    def matches(cls, extension, header):
        signatures = cls.SIGNATURES.get(extension)
        if not signatures:
            return True
        if extension == ".pdf":
            return any(signature in header[:cls.PDF_HEADER_WINDOW] for _, signature in signatures)
        return any(header[offset:offset + len(signature)] == signature for offset, signature in signatures)

    @classmethod
    def validate_container(cls, path, extension, header):
        required_member = cls.ZIP_DOCUMENT_MEMBERS.get(extension)
        if required_member is None or header.startswith(cls.OLE_SIGNATURE):
            return ""
        try:
            with zipfile.ZipFile(path) as archive:
                if archive.testzip() is not None:
                    return "ZIP container has a corrupt member"
                if required_member not in archive.namelist():
                    return f"ZIP container is missing {required_member}"
        except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
            return "ZIP container is incomplete or invalid"
        return ""
