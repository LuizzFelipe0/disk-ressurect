from infrastructure.disk.output_safety import OutputSafetyGuard
from infrastructure.filesystems.ntfs.readers.file_content_reader import NTFSFileContentReader
from infrastructure.filesystems.ntfs.readers.file_signature_validator import FileSignatureValidator
from infrastructure.recovery.extractor import Extractor
from modules.recovery.service import RecoveryWorkflow


def make_recovery_workflow(disk_factory, output_guard=None):
    return RecoveryWorkflow(
        disk_factory,
        output_guard if output_guard is not None else OutputSafetyGuard(),
        NTFSFileContentReader,
        FileSignatureValidator,
        Extractor,
    )
