"""Consumo de RAM do próprio processo (monitor do app) e liberação de memória ociosa."""
import gc
import sys

_win = None          # estruturas do ctypes, criadas UMA vez (criar a cada chamada vaza memória)


def _win_setup():
    global _win
    if _win is not None:
        return _win
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

    kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
    psapi.EmptyWorkingSet.restype = wintypes.BOOL
    _win = (ctypes, PMC, kernel32, psapi)
    return _win


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
    ctypes, PMC, kernel32, psapi = _win_setup()
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return None, None
    return pmc.WorkingSetSize / 1048576, pmc.PagefileUsage / 1048576


def trim():
    """Devolve ao sistema a memória que o app não está usando agora.

    - coleta o lixo do Python;
    - Windows: esvazia o working set (as páginas realmente usadas voltam sozinhas,
      o resto — principalmente código das DLLs do FFmpeg que não é usado — fica de fora);
    - Linux: malloc_trim.
    """
    try:
        gc.collect()
        if sys.platform == "win32":
            ctypes, PMC, kernel32, psapi = _win_setup()
            psapi.EmptyWorkingSet(kernel32.GetCurrentProcess())
        elif sys.platform.startswith("linux"):
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass
