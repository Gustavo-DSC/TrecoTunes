"""Leitura do consumo de RAM do próprio processo (para o monitor do app)."""
import sys


def usage_mb():
    """Retorna (working_set_mb, privado_mb). privado_mb pode ser None."""
    try:
        if sys.platform == "win32":
            return _win_usage()
        import os
        with open("/proc/self/statm") as f:
            pages = int(f.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / 1048576, None
    except Exception:
        return None, None


def _win_usage():
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    get_proc = ctypes.windll.kernel32.GetCurrentProcess
    get_proc.restype = wintypes.HANDLE
    get_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    if not get_info(get_proc(), ctypes.byref(pmc), pmc.cb):
        return None, None
    return pmc.WorkingSetSize / 1048576, pmc.PagefileUsage / 1048576
