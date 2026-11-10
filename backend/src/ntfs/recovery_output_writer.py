import os
import secrets
import sys
import tempfile

from infrastructure.filesystem.user_ownership import (
    ensure_pkexec_user_owned_directory,
    open_pkexec_safe_directory,
    set_pkexec_user_ownership_fd,
)


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

        try:
            ensure_pkexec_user_owned_directory(os.path.dirname(destination))
        except OSError as exc:
            raise UnsafeRecoveryPath("Output path contains an unsafe or inaccessible directory") from exc
        return destination, destination + self.PARTIAL_SUFFIX

    @staticmethod
    def open_temporary(temporary_path):
        directory = os.path.dirname(temporary_path)
        prefix = os.path.basename(temporary_path) + "."
        if sys.platform.startswith("linux") and os.open in os.supports_dir_fd:
            directory_fd = open_pkexec_safe_directory(directory)
            try:
                for _ in range(32):
                    name = f"{prefix}{secrets.token_hex(12)}.tmp"
                    try:
                        descriptor = os.open(
                            name,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL
                            | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                            0o600,
                            dir_fd=directory_fd,
                        )
                        break
                    except FileExistsError:
                        continue
                else:
                    raise FileExistsError("Could not allocate a unique recovery temporary file")
                unique_path = os.path.join(directory, name)
            finally:
                os.close(directory_fd)
        else:
            descriptor, unique_path = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
        try:
            set_pkexec_user_ownership_fd(descriptor)
        except BaseException:
            os.close(descriptor)
            RecoveryOutputWriter.discard(unique_path)
            raise
        return os.fdopen(descriptor, "wb"), unique_path

    @staticmethod
    def publish(temporary_path, destination):
        if sys.platform.startswith("linux") and os.replace in os.supports_dir_fd:
            directory_fd = open_pkexec_safe_directory(os.path.dirname(destination))
            try:
                os.replace(
                    os.path.basename(temporary_path),
                    os.path.basename(destination),
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
            finally:
                os.close(directory_fd)
            return
        os.replace(temporary_path, destination)

    @staticmethod
    def write_chunk(output, data):
        if data and output.write(data) != len(data):
            raise OSError(f"Short output write: wrote fewer than {len(data)} bytes")

    @staticmethod
    def discard(temporary_path):
        if not temporary_path:
            return
        if sys.platform.startswith("linux") and os.unlink in os.supports_dir_fd:
            try:
                directory_fd = open_pkexec_safe_directory(os.path.dirname(temporary_path))
                try:
                    os.unlink(os.path.basename(temporary_path), dir_fd=directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
            return
        if os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                pass
