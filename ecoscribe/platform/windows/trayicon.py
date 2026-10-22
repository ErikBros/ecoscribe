"""The tray icon without the freeze (dictado-434): pystray turns the picture into an .ico file and
loads it again on every change, on the thread that sets it. A freeze dump caught the main thread
seconds deep in that. Here each state's picture is converted once; a change only swaps the handle."""
from __future__ import annotations


def cached(base):
    """A subclass of pystray's Icon (`base`) that keeps one icon handle per picture."""
    class CachedIcon(base):
        def __init__(self, *a, **k):
            self._handles = {}
            super().__init__(*a, **k)

        def _release_icon(self):
            self._icon_handle = None  # the handle stays in the cache for the next time this picture shows

        def _assert_icon_handle(self):
            key = id(self.icon)
            if key not in self._handles:
                self._icon_handle = None
                super()._assert_icon_handle()  # the one conversion for this picture
                self._handles[key] = self._icon_handle
            self._icon_handle = self._handles[key]
    return CachedIcon
