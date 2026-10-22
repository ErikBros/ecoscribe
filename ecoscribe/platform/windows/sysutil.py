"""winutil on Windows: single instance by named mutex, CUDA DLL dirs (the GPU runtime pack), DPI, a hard exit without DLL detach."""
from __future__ import annotations

import ctypes
import os
import site
import sys
from pathlib import Path


_mutex = None


def single_instance(name: str) -> bool:
    """True if we are the only holder of the named mutex."""
    global _mutex
    import win32api
    import win32event
    import winerror

    h = win32event.CreateMutex(None, False, name)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        win32api.CloseHandle(h)  # don't keep someone else's mutex alive (the restart wait loop polls this)
        return False
    _mutex = h
    return True


def release_instance() -> None:
    """Let a freshly spawned copy take the single-instance mutex."""
    global _mutex
    if _mutex is not None:
        import win32api
        win32api.CloseHandle(_mutex)
        _mutex = None


def cuda_roots() -> list[str]:
    """Folders with nvidia/<lib>/bin under them, in search order: the GPU runtime pack (dictado-7e1),
    the app's own folder (installers <= 1.17 bundled the DLLs there), then site-packages (a source run)."""
    roots = []
    try:
        from ...gpu_runtime import dll_root
        rt = dll_root()
        if rt is not None:
            roots.append(str(rt))
    except Exception:  # never stop the app over it: CUDA then fails and the engine runs on the CPU
        pass
    if getattr(sys, "frozen", False):
        roots.append(getattr(sys, "_MEIPASS", str(Path(sys.executable).parent)))
    roots += list(site.getsitepackages())
    try:
        roots.append(site.getusersitepackages())
    except Exception:
        pass
    return roots


_added: set[str] = set()


def add_cuda_dll_dirs() -> list[str]:
    """Make the CUDA 12 DLLs (nvidia/*/bin) loadable by ctranslate2: os.add_dll_directory for Python's
    loader, PATH for ctranslate2's own LoadLibrary of cublas. Called again once the runtime arrives."""
    added = []
    for root in cuda_roots():
        nv = Path(root) / "nvidia"
        if not nv.is_dir():
            continue
        for bin_dir in nv.glob("*/bin"):
            if str(bin_dir) in _added:
                continue
            try:
                os.add_dll_directory(str(bin_dir))
            except (OSError, AttributeError):
                continue
            _added.add(str(bin_dir))
            added.append(str(bin_dir))
    if added:  # in root order, ahead of what was there: the runtime pack wins over any other copy
        os.environ["PATH"] = os.pathsep.join(added + [os.environ.get("PATH", "")])
    return added


def set_dpi_aware() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def hard_exit(code: int = 0) -> None:
    """Exit without interpreter teardown.

    CTranslate2/CUDA crash with 0xC0000409 in their DLL detach code after a long
    (>30 s) transcription, measured 2026-10-02 in frozen and plain Python, even
    with os._exit. TerminateProcess skips DLL detach. Callers clean up first (mic,
    mute, tray); this flushes logs and ends the process.
    """
    import logging
    try:
        sys.stdout and sys.stdout.flush()
        sys.stderr and sys.stderr.flush()
        logging.shutdown()
    finally:
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.TerminateProcess.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        k32.TerminateProcess(k32.GetCurrentProcess(), code)
        os._exit(code)  # not reached
