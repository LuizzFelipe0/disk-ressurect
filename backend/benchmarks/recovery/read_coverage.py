"""Bounded, opt-in measurement wrapper for existing read_at() source contracts."""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import sys
import threading


class _IntervalLedger:
    def __init__(self, interval_cap):
        self.interval_cap = max(1, int(interval_cap))
        self.intervals = []
        self.truncated = False

    @property
    def unique_bytes(self):
        return sum(end - start for start, end in self.intervals)

    def add(self, start, end):
        if self.truncated or end <= start:
            return
        merged = []
        insert_start, insert_end = start, end
        inserted = False
        for left, right in self.intervals:
            if right < insert_start:
                merged.append((left, right))
            elif insert_end < left:
                if not inserted:
                    merged.append((insert_start, insert_end))
                    inserted = True
                merged.append((left, right))
            else:
                insert_start = min(insert_start, left)
                insert_end = max(insert_end, right)
        if not inserted:
            merged.append((insert_start, insert_end))
        if len(merged) > self.interval_cap:
            self.truncated = True
            self.intervals.clear()
            return
        self.intervals = merged


class InstrumentedReader:
    """Wrap a positional reader, tracking bounded global and per-stage byte coverage."""

    def __init__(self, reader, *, size, interval_cap=65_536, capture_events=False):
        self.reader = reader
        self.size = int(size)
        self.size_bytes = self.size
        self.bytes_per_sector = int(getattr(reader, "bytes_per_sector", 512) or 512)
        self.interval_cap = int(interval_cap)
        self._current_stage = "unclassified"
        self._lock = threading.RLock()
        self._global = _IntervalLedger(interval_cap)
        self._stages = {}
        self._counters = Counter()
        self._size_histogram = Counter()
        self._operation_cap = 1_000_000
        self._operations = 0
        self.event_cap = 4096
        self.capture_events = bool(capture_events)
        self.events = []

    @contextmanager
    def stage(self, name):
        previous = self._current_stage
        self._current_stage = str(name)
        try:
            yield
        finally:
            self._current_stage = previous

    def read_at(self, offset, size):
        offset, size = int(offset), int(size)
        stage = self._infer_stage(self._current_stage)
        with self._lock:
            if self._operations >= self._operation_cap:
                raise RuntimeError("Benchmark read-operation accounting cap reached")
            self._operations += 1
            self._counters[(stage, "requested")] += size
            self._counters[(stage, "operations")] += 1
            self._size_histogram[(stage, self._bucket(size))] += 1
        try:
            data = bytes(self.reader.read_at(offset, size))
        except Exception:
            with self._lock:
                self._counters[(stage, "errors")] += 1
                if self.capture_events and len(self.events) < self.event_cap:
                    self.events.append((stage, offset, size, 0, "error"))
            raise
        with self._lock:
            self._counters[(stage, "successful")] += len(data)
            if len(data) != size:
                self._counters[(stage, "short_reads")] += 1
            self._global.add(offset, offset + len(data))
            self._stages.setdefault(stage, _IntervalLedger(self.interval_cap)).add(
                offset, offset + len(data),
            )
            if self.capture_events and len(self.events) < self.event_cap:
                status = "short" if len(data) != size else "ok"
                self.events.append((stage, offset, size, len(data), status))
        return data

    @staticmethod
    def _bucket(size):
        if size <= 4096:
            return "0-4KiB"
        if size <= 64 * 1024:
            return "4-64KiB"
        if size <= 1024 * 1024:
            return "64KiB-1MiB"
        return ">1MiB"

    @staticmethod
    def _infer_stage(default):
        if default not in {"unclassified", "content_carving"}:
            return default
        frame = sys._getframe(1)
        checked = 0
        saw_carver_scan = False
        while frame is not None and checked < 8:
            name = frame.f_code.co_name
            instance = frame.f_locals.get("self")
            class_name = getattr(instance, "__class__", type(None)).__name__
            if name == "_restore_candidates":
                return "candidate_restoration"
            if name.startswith("_read_") or name == "_read_candidate_bytes":
                return "candidate_validation"
            if name == "scan" and class_name == "RawContentCarver":
                saw_carver_scan = True
            checked += 1
            frame = frame.f_back
        if saw_carver_scan:
            return "signature_discovery"
        return default

    def report(self):
        stages = {}
        for stage in sorted({key[0] for key in self._counters}):
            stage_intervals = self._stages.get(stage, _IntervalLedger(self.interval_cap))
            stages[stage] = {
                "requestedBytes": self._counters[(stage, "requested")],
                "successfulBytes": self._counters[(stage, "successful")],
                "uniqueBytes": (None if stage_intervals.truncated else stage_intervals.unique_bytes),
                "repeatedBytes": (None if stage_intervals.truncated else
                                  self._counters[(stage, "successful")] - stage_intervals.unique_bytes),
                "operations": self._counters[(stage, "operations")],
                "errors": self._counters[(stage, "errors")],
                "shortReads": self._counters[(stage, "short_reads")],
                "readSizeBuckets": {
                    bucket: self._size_histogram[(stage, bucket)]
                    for bucket in ("0-4KiB", "4-64KiB", "64KiB-1MiB", ">1MiB")
                },
                "intervalLedgerTruncated": stage_intervals.truncated,
            }
        total_success = sum(self._counters[(stage, "successful")] for stage in stages)
        global_unique = None if self._global.truncated else self._global.unique_bytes
        return {
            "requestedBytes": sum(self._counters[(stage, "requested")] for stage in stages),
            "successfulBytes": total_success,
            "globalUniqueBytes": global_unique,
            "globalRepeatedBytes": None if global_unique is None else total_success - global_unique,
            "readAmplification": (None if not global_unique else total_success / global_unique),
            "globalIntervalLedgerTruncated": self._global.truncated,
            "readOperations": self._operations,
            "stages": stages,
        }
