"""Allocation-map evidence for NTFS file data runs.

An allocated bit can mean that old file data was reused, but it can also be
stale or inconsistent metadata. Callers should present this as evidence, not
as a rule for rejecting an otherwise valid recovery candidate.
"""


class ClusterAllocationEvidence:
    """Classify orphan data-run clusters while ``$Bitmap`` is streamed once."""

    DEFAULT_UNCERTAIN_RANGE_BYTES = 128 * 1024 * 1024
    DEFAULT_UNCERTAIN_RANGE_COUNT = 4096

    def __init__(self, records, cluster_count):
        self.cluster_count = max(0, int(cluster_count))
        self.records = dict(records or {})
        self.bytes_observed = 0
        self._ranges = {}
        self._counts = {}
        for record_id, record in self.records.items():
            allocated_runs = []
            sparse_clusters = 0
            out_of_range_clusters = 0
            for lcn, run_clusters in getattr(record, "data_runs", ()):
                run_clusters = int(run_clusters)
                if run_clusters <= 0:
                    continue
                if lcn is None:
                    sparse_clusters += run_clusters
                    continue
                run_start = int(lcn)
                run_end = run_start + run_clusters
                clipped_start = max(0, run_start)
                clipped_end = min(self.cluster_count, run_end)
                if clipped_start < clipped_end:
                    allocated_runs.append((clipped_start, clipped_end))
                out_of_range_clusters += run_clusters - max(0, clipped_end - clipped_start)
            self._ranges[record_id] = allocated_runs
            self._counts[record_id] = {
                "allocatedClusters": 0,
                "freeClusters": 0,
                "unknownClusters": out_of_range_clusters,
                "sparseClusters": sparse_clusters,
            }

    def consume(self, bitmap_chunk, bitmap_byte_offset):
        """Consume one contiguous chunk of bitmap bytes at its file offset."""
        data = bytes(bitmap_chunk)
        if not data:
            return
        self.bytes_observed = max(self.bytes_observed,
            int(bitmap_byte_offset) + len(data))
        chunk_start_bit = int(bitmap_byte_offset) * 8
        chunk_end_bit = chunk_start_bit + len(data) * 8
        for record_id, runs in self._ranges.items():
            counts = self._counts[record_id]
            for run_start, run_end in runs:
                overlap_start = max(run_start, chunk_start_bit)
                overlap_end = min(run_end, chunk_end_bit, self.cluster_count)
                if overlap_start >= overlap_end:
                    continue
                first_byte = overlap_start // 8
                last_byte = (overlap_end - 1) // 8
                allocated = 0
                observed = 0
                for absolute_byte in range(first_byte, last_byte + 1):
                    first_bit = overlap_start % 8 if absolute_byte == first_byte else 0
                    last_bit = ((overlap_end - 1) % 8 + 1
                        if absolute_byte == last_byte else 8)
                    mask = ((1 << last_bit) - 1) ^ ((1 << first_bit) - 1)
                    value = data[absolute_byte - int(bitmap_byte_offset)]
                    allocated += (value & mask).bit_count()
                    observed += mask.bit_count()
                counts["allocatedClusters"] += allocated
                counts["freeClusters"] += observed - allocated

    def to_dict(self):
        result = []
        for record_id, counts in self._counts.items():
            total_non_sparse = sum(end - start for start, end in self._ranges[record_id])
            total_requested = total_non_sparse + counts["unknownClusters"]
            observed = counts["allocatedClusters"] + counts["freeClusters"]
            # Bitmap reads can stop early. Clusters beyond the bytes read remain
            # unknown instead of being treated as free.
            unknown = max(counts["unknownClusters"], total_requested - observed)
            if unknown:
                status = "partially_observed" if observed else "unavailable"
            elif counts["allocatedClusters"] and counts["freeClusters"]:
                status = "mixed"
            elif counts["allocatedClusters"]:
                status = "allocated"
            elif counts["freeClusters"]:
                status = "free"
            else:
                status = "no_non_sparse_runs"
            result.append({
                "recordId": record_id,
                "status": status,
                **counts,
                "unknownClusters": unknown,
                "bitmapObservedClusters": observed,
            })
        return result

    def uncertain_content_ranges(
        self, volume_start, cluster_size, *, max_bytes=None, max_ranges=None,
    ):
        """Build separately bounded raw-scan ranges from uncertain orphan data runs.

        Bitmap-unobserved ranges are restricted to valid in-volume LCNs beyond
        the contiguous observed bitmap prefix. Possibly-reused ranges include
        complete in-volume runs for orphan records with any allocated bits.
        """
        volume_start = int(volume_start)
        cluster_size = int(cluster_size)
        max_bytes = max(0, int(self.DEFAULT_UNCERTAIN_RANGE_BYTES if max_bytes is None else max_bytes))
        max_ranges = max(0, int(self.DEFAULT_UNCERTAIN_RANGE_COUNT if max_ranges is None else max_ranges))
        if cluster_size <= 0 or max_bytes == 0 or max_ranges == 0:
            return {"bitmapUnobserved": (), "possiblyReused": (), "truncated": False}

        statuses = {item["recordId"]: item for item in self.to_dict()}
        observed_clusters = self.bytes_observed * 8
        unobserved = []
        reused = []
        for record_id, runs in self._ranges.items():
            evidence = statuses.get(record_id, {})
            include_reused = int(evidence.get("allocatedClusters", 0)) > 0
            for run_start, run_end in runs:
                unobserved_start = max(run_start, observed_clusters)
                if unobserved_start < run_end:
                    unobserved.append((unobserved_start, run_end))
                if include_reused:
                    reused.append((run_start, run_end))

        unobserved_ranges, unobserved_truncated = self._physical_ranges(
            unobserved, volume_start, cluster_size, max_bytes, max_ranges,
        )
        reused_ranges, reused_truncated = self._physical_ranges(
            reused, volume_start, cluster_size, max_bytes, max_ranges,
        )
        return {
            "bitmapUnobserved": unobserved_ranges,
            "possiblyReused": reused_ranges,
            "bitmapUnobservedTruncated": unobserved_truncated,
            "possiblyReusedTruncated": reused_truncated,
        }

    @staticmethod
    def _physical_ranges(ranges, volume_start, cluster_size, max_bytes, max_ranges):
        merged = []
        for start, end in sorted(ranges):
            if end <= start:
                continue
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        cluster_budget = max_bytes // cluster_size
        retained_clusters = 0
        result = []
        truncated = False
        for start, end in merged:
            if len(result) >= max_ranges or retained_clusters >= cluster_budget:
                truncated = True
                break
            count = min(end - start, cluster_budget - retained_clusters)
            if count <= 0:
                truncated = True
                break
            result.append((
                volume_start + start * cluster_size,
                volume_start + (start + count) * cluster_size,
            ))
            retained_clusters += count
            if count < end - start:
                truncated = True
                break
        return tuple(result), truncated


class FreeClusterRangeCollector:
    """Retain a bounded prefix of free-cluster byte ranges for content carving."""

    DEFAULT_MAX_BYTES = 1024 * 1024 * 1024
    DEFAULT_MAX_RANGES = 8192

    def __init__(self, volume_start, cluster_size, cluster_count, *, max_bytes=DEFAULT_MAX_BYTES,
                 max_ranges=DEFAULT_MAX_RANGES):
        self.volume_start = int(volume_start)
        self.cluster_size = int(cluster_size)
        self.cluster_count = max(0, int(cluster_count))
        self.max_bytes = max(0, int(max_bytes))
        self.max_ranges = max(0, int(max_ranges))
        self.ranges = []
        self._run_start = None
        self._run_end = None
        self._retained_bytes = 0
        self.truncated = False

    def consume(self, bitmap_chunk, bitmap_byte_offset):
        if self.truncated or self.max_bytes == 0 or self.max_ranges == 0:
            self.truncated = True
            return
        data = bytes(bitmap_chunk)
        first_cluster = int(bitmap_byte_offset) * 8
        for byte_index, value in enumerate(data):
            cluster = first_cluster + byte_index * 8
            valid = min(8, self.cluster_count - cluster)
            if valid <= 0:
                break
            # A zero bitmap byte represents eight adjacent free clusters. Handle
            # this common case in one step; inspect partial bytes bit by bit.
            if value == 0 and valid == 8:
                self._consume_run(cluster, cluster + 8)
                continue
            bit = 0
            while bit < valid:
                is_free = not bool(value & (1 << bit))
                run_end = bit + 1
                while run_end < valid and (not bool(value & (1 << run_end))) == is_free:
                    run_end += 1
                if is_free:
                    self._consume_run(cluster + bit, cluster + run_end)
                else:
                    self._flush_run()
                bit = run_end

    def finish(self):
        self._flush_run()
        return {
            "ranges": tuple(self.ranges),
            "retainedBytes": self._retained_bytes,
            "rangeCapBytes": self.max_bytes,
            "truncated": self.truncated,
        }

    def _consume_run(self, start, end):
        if self._run_end == start:
            self._run_end = end
        else:
            self._flush_run()
            if not self.truncated:
                self._run_start, self._run_end = start, end
        if self._run_start is not None:
            pending_bytes = (self._run_end - self._run_start) * self.cluster_size
            if self._retained_bytes + pending_bytes >= self.max_bytes:
                allowed = max(0, self.max_bytes - self._retained_bytes)
                allowed_clusters = allowed // self.cluster_size
                self._run_end = self._run_start + allowed_clusters
                self.truncated = True
                self._flush_run()

    def _flush_run(self):
        if self._run_start is None or self._run_end is None:
            return
        cluster_count = self._run_end - self._run_start
        if cluster_count > 0:
            byte_count = cluster_count * self.cluster_size
            self.ranges.append((
                self.volume_start + self._run_start * self.cluster_size,
                self.volume_start + self._run_end * self.cluster_size,
            ))
            self._retained_bytes += byte_count
            if len(self.ranges) >= self.max_ranges or self._retained_bytes >= self.max_bytes:
                self.truncated = True
        self._run_start = None
        self._run_end = None
