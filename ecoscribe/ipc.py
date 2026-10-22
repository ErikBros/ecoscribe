"""Tiny IPC between the background app and the window: one named event + process launch
(per platform: ecoscribe/platform/windows/ipc.py, ecoscribe/platform/macos/ipc.py)."""
from __future__ import annotations

import sys
from pathlib import Path

RELOAD_EVENT = "Local\\EcoscribeReload"
UI_MUTEX = "Local\\EcoscribeUI"
UI_TITLE = "Ecoscribe"
PAGE_FILE = "ui_page.txt"  # Windows: the page an open window should show next (Api.take_page reads it once)


def self_command(args: list[str]) -> list[str]:
    """How to start another copy of this program (installed exe or dev Python)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "ecoscribe", *args]


def _package_parent() -> str:
    return str(Path(__file__).resolve().parent.parent)


def open_ui(page: str | None = None) -> None:
    """Open the window, or focus it if it's already open and turn it to `page`."""
    if focus_ui():
        if page:
            ask_page(page)
        return
    spawn(["--ui"] + (["--page", page] if page else []))


def ask_page(page: str) -> None:
    """Tell the open window to show `page` (it checks every second): a notice's button, a box's Open."""
    from . import paths
    try:
        (paths.data_dir() / PAGE_FILE).write_text(page, encoding="utf-8")
    except OSError:
        pass


if sys.platform == "darwin":  # macOS: same names over Unix sockets (ecoscribe/platform/macos/ipc.py)
    from .platform.macos.ipc import (RELOAD_EVENT, UI_FOCUS, UI_MUTEX, UI_TITLE, ReloadWatcher, _package_parent,  # noqa: F811,F401
                          focus_ui, open_ui, self_command, signal_reload, spawn)
else:  # named events, FindWindow (ecoscribe/platform/windows/ipc.py)
    from .platform.windows.ipc import ReloadWatcher, focus_ui, signal_reload, spawn  # noqa: F401
