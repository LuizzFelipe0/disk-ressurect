import os
import tempfile

from infrastructure.filesystem.user_ownership import set_pkexec_user_ownership


class UnsafeRecoveryPath(ValueError):
    pass


class RecoveryOutputWriter:
    PARTIAL_SUFFIX = ".partial"

    def prepare_target(self, output_directory, relative_path):
        root = os.path.abspath(output_directory)
        destination = os.path.abspath(os.path.join(root, relative_path))
        try:
            within_root = os.path.commonpath((root, destination)) == root
        except ValueError:
            within_root = False
        if not within_root:
            raise UnsafeRecoveryPath("Output path escapes the recovery directory")

        parent = os.path.dirname(destination)
        missing_directories = []
        if not os.path.exists(root):
            os.makedirs(root, exist_ok=True)
            missing_directories.append(root)
        relative_parent = os.path.relpath(parent, root)
        cursor = root
        if relative_parent != os.curdir:
            for segment in relative_parent.split(os.sep):
                cursor = os.path.join(cursor, segment)
                try:
                    os.mkdir(cursor)
                except FileExistsError:
                    pass
                else:
                    missing_directories.append(cursor)
        real_root = os.path.realpath(root)
        real_parent = os.path.realpath(parent)
        try:
            real_parent_is_safe = os.path.commonpath((real_root, real_parent)) == real_root
        except ValueError:
            real_parent_is_safe = False
        if not real_parent_is_safe:
            raise UnsafeRecoveryPath("Output path resolves outside the recovery directory")
        for directory in reversed(missing_directories):
            set_pkexec_user_ownership(directory)
        return destination, destination + self.PARTIAL_SUFFIX

    @staticmethod
    def open_temporary(temporary_path):
        directory = os.path.dirname(temporary_path)
        prefix = os.path.basename(temporary_path) + "."
        descriptor, unique_path = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
        return os.fdopen(descriptor, "wb"), unique_path

    @staticmethod
    def prepare_file_for_publish(temporary_path):
        set_pkexec_user_ownership(temporary_path)

    @staticmethod
    def publish(temporary_path, destination):
        os.replace(temporary_path, destination)

    @staticmethod
    def write_chunk(output, data):
        if data and output.write(data) != len(data):
            raise OSError(f"Short output write: wrote fewer than {len(data)} bytes")

    @staticmethod
    def discard(temporary_path):
        if temporary_path and os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                pass
