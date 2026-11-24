class FileContentError(Exception):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status
        self.reason = reason


class NTFSFileContentReader:
    READ_CHUNK_SIZE = 4 * 1024 * 1024
    MAX_NAMED_STREAM_READ_BYTES = 64 * 1024 * 1024

    def __init__(
        self, disk, volume_start, cluster_size, chunk_size=READ_CHUNK_SIZE,
        volume_size_bytes=None,
    ):
        self.disk = disk
        self.volume_start = int(volume_start)
        self.cluster_size = int(cluster_size)
        self.chunk_size = max(1, int(chunk_size))
        self.volume_size_bytes = (
            None if volume_size_bytes is None else int(volume_size_bytes)
        )

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
                    relative_offset = lcn * self.cluster_size + run_offset
                    if (self.volume_size_bytes is not None
                            and (relative_offset < 0
                                 or relative_offset + request_size > self.volume_size_bytes)):
                        raise FileContentError(
                            "data_run_out_of_volume",
                            "File data run extends beyond the selected NTFS volume",
                        )
                    disk_offset = self.volume_start + relative_offset
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

    def read_named_stream(self, node, stream_name, max_bytes=MAX_NAMED_STREAM_READ_BYTES):
        """Return a bounded prefix of a complete named ``$DATA`` stream.

        The hard cap is 64 MiB. When the declared stream is larger than the
        requested budget, only its prefix is returned; callers must compare
        the returned length with the descriptor's ``file_size`` and report the
        scan as partial. Incomplete/duplicate/extension-backed descriptors are
        refused rather than guessed.
        """
        try:
            requested_budget = int(max_bytes)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Named-stream read budget must be an integer") from exc
        if requested_budget <= 0:
            raise ValueError("Named-stream read budget must be positive")
        budget = min(requested_budget, self.MAX_NAMED_STREAM_READ_BYTES)

        record = getattr(node, "record", node)
        getter = getattr(record, "get_named_data_stream", None)
        if callable(getter):
            stream = getter(stream_name)
        else:
            streams = getattr(record, "named_data_streams", {}) or {}
            stream = streams.get(str(stream_name).casefold())
        if stream is None:
            raise FileContentError("missing_named_stream", f"Named stream {stream_name!r} was not found")
        if not bool(getattr(stream, "is_complete", False)):
            reasons = ", ".join(getattr(stream, "incomplete_reasons", ()) or ())
            detail = f": {reasons}" if reasons else ""
            raise FileContentError("incomplete_named_stream", f"Named stream mapping is incomplete{detail}")

        try:
            expected_size = int(stream.file_size)
        except (AttributeError, TypeError, ValueError, OverflowError) as exc:
            raise FileContentError("invalid_named_stream", "Named stream has an invalid size") from exc
        if expected_size < 0:
            raise FileContentError("invalid_named_stream", "Named stream size cannot be negative")
        read_size = min(expected_size, budget)
        resident_data = getattr(stream, "resident_data", None)
        if bool(getattr(stream, "is_resident", resident_data is not None)):
            if resident_data is None or len(resident_data) != expected_size:
                raise FileContentError("incomplete_named_stream", "Resident named stream size does not match its data")
            return bytes(resident_data[:read_size])

        if read_size == 0:
            return b""
        runs = tuple(getattr(stream, "data_runs", ()) or ())
        if not runs:
            raise FileContentError("missing_named_stream_runs", "Named stream has no data runs")
        if self.volume_size_bytes is None or self.volume_size_bytes <= 0:
            raise FileContentError(
                "volume_bounds_unavailable",
                "A volume size is required before reading a non-resident named stream",
            )

        chunks = []
        remaining_file_bytes = read_size
        bytes_written = 0
        for lcn, cluster_count in runs:
            if remaining_file_bytes <= 0:
                break
            cluster_count = int(cluster_count)
            if cluster_count <= 0:
                raise FileContentError("invalid_named_stream_runlist", "A named-stream run has non-positive length")
            run_remaining = min(cluster_count * self.cluster_size, remaining_file_bytes)
            run_offset = 0
            while run_remaining:
                request_size = min(run_remaining, self.chunk_size, budget - bytes_written)
                if request_size <= 0:
                    break
                if lcn is None:
                    chunk = bytes(request_size)
                else:
                    relative_offset = int(lcn) * self.cluster_size + run_offset
                    if (relative_offset < 0
                            or relative_offset + request_size > self.volume_size_bytes):
                        raise FileContentError(
                            "named_stream_out_of_volume",
                            "Named-stream run extends beyond the selected NTFS volume",
                        )
                    disk_offset = self.volume_start + relative_offset
                    chunk = self.disk.read_at(disk_offset, request_size)
                    if len(chunk) != request_size:
                        raise FileContentError(
                            "incomplete_read",
                            f"Read {len(chunk)} of {request_size} bytes at disk offset {disk_offset}",
                        )
                chunks.append(bytes(chunk))
                remaining_file_bytes -= request_size
                bytes_written += request_size
                run_remaining -= request_size
                run_offset += request_size
        if remaining_file_bytes:
            raise FileContentError(
                "incomplete_named_stream",
                f"Named-stream runs ended with {remaining_file_bytes} bytes missing",
            )
        return b"".join(chunks)
