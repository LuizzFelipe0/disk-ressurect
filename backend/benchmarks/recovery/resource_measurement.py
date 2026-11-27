"""Standard-library resource measurements used only by the opt-in harness."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import platform
import time
import tracemalloc


class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def process_memory_bytes():
    """Return current/peak process working set using Windows PSAPI when present."""
    if os.name != "nt":
        return {"currentWorkingSetBytes": None, "peakWorkingSetBytes": None,
                "measurement": "unavailable"}
    counters = _PROCESS_MEMORY_COUNTERS_EX()
    counters.cb = ctypes.sizeof(counters)
    psapi = ctypes.WinDLL("Psapi.dll")
    kernel32 = ctypes.WinDLL("Kernel32.dll")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.argtypes = []
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_PROCESS_MEMORY_COUNTERS_EX), wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    ok = psapi.GetProcessMemoryInfo(
        kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb,
    )
    if not ok:
        return {"currentWorkingSetBytes": None, "peakWorkingSetBytes": None,
                "measurement": "GetProcessMemoryInfo failed"}
    return {
        "currentWorkingSetBytes": int(counters.WorkingSetSize),
        "peakWorkingSetBytes": int(counters.PeakWorkingSetSize),
        "measurement": "Windows process working set",
    }


def measure(callable_):
    before_memory = process_memory_bytes()
    cpu_start = time.process_time()
    wall_start = time.perf_counter()
    tracemalloc.start()
    try:
        value = callable_()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return value, {
        "cpuSeconds": time.process_time() - cpu_start,
        "wallSeconds": time.perf_counter() - wall_start,
        "tracemallocPeakBytes": int(peak),
        "processMemoryBefore": before_memory,
        "processMemoryAfter": process_memory_bytes(),
        "python": platform.python_version(),
    }
