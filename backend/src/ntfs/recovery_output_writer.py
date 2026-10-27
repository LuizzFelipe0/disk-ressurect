import os


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

        os.makedirs(os.path.dirname(destination), exist_ok=True)
        real_root = os.path.realpath(root)
        real_parent = os.path.realpath(os.path.dirname(destination))
        try:
            real_parent_is_safe = os.path.commonpath((real_root, real_parent)) == real_root
        except ValueError:
            real_parent_is_safe = False
        if not real_parent_is_safe:
            raise UnsafeRecoveryPath("Output path resolves outside the recovery directory")
        return destination, destination + self.PARTIAL_SUFFIX

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
