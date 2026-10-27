class FileContentError(Exception):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status
        self.reason = reason


class NTFSFileContentReader:
    READ_CHUNK_SIZE = 4 * 1024 * 1024

    def __init__(self, disk, volume_start, cluster_size, chunk_size=READ_CHUNK_SIZE):
        self.disk = disk
        self.volume_start = int(volume_start)
        self.cluster_size = int(cluster_size)
        self.chunk_size = max(1, int(chunk_size))

    def iter_chunks(self, node):
        record = node.record
        expected_size = int(record.file_size)
        if getattr(record, "data_is_complete", True) is False:
            raise FileContentError("incomplete_mft", "MFT data attributes are incomplete")

        resident_data = record.resident_data
        if resident_data is not None:
            payload = bytes(resident_data)
            if payload:
                yield payload
            if len(payload) != expected_size:
                raise FileContentError(
                    "incomplete_read", "Resident data length does not match the MFT size",
                )
            return

        runs = record.data_runs
        if not runs:
            raise FileContentError("missing_data_runs", "No data runs are available")

        remaining_file_bytes = expected_size
        for lcn, cluster_count in runs:
            if remaining_file_bytes <= 0:
                break
            if cluster_count <= 0:
                raise FileContentError("invalid_runlist", "A data run has a non-positive length")

            run_remaining = min(cluster_count * self.cluster_size, remaining_file_bytes)
            run_offset = 0
            while run_remaining:
                request_size = min(run_remaining, self.chunk_size)
                if lcn is None:
                    chunk = bytes(request_size)
                else:
                    disk_offset = self.volume_start + lcn * self.cluster_size + run_offset
                    chunk = self.disk.read_at(disk_offset, request_size)
                    if chunk:
                        yield chunk
                    if len(chunk) != request_size:
                        raise FileContentError(
                            "incomplete_read",
                            f"Read {len(chunk)} of {request_size} bytes at disk offset {disk_offset}",
                        )
                    remaining_file_bytes -= len(chunk)
                    run_remaining -= len(chunk)
                    run_offset += len(chunk)
                    continue

                yield chunk
                remaining_file_bytes -= len(chunk)
                run_remaining -= len(chunk)
                run_offset += len(chunk)

        if remaining_file_bytes:
            raise FileContentError(
                "incomplete_data", f"Data runs ended with {remaining_file_bytes} bytes missing",
            )
