"""dictado-434: each tray picture is converted to an icon once, however often the state changes."""
from ecoscribe.platform.windows.trayicon import cached


class FakeIcon:  # pystray's Icon as far as the cache touches it
    def __init__(self, image):
        self.icon, self._icon_handle, self.converted, self.destroyed = image, None, [], []

    def _assert_icon_handle(self):
        if self._icon_handle:
            return
        self.converted.append(self.icon)
        self._icon_handle = f"handle-{self.icon}"

    def _release_icon(self):
        self.destroyed.append(self._icon_handle)
        self._icon_handle = None

    def set(self, image):  # what the icon setter + _update_icon do
        self.icon = image
        self._release_icon()
        self._assert_icon_handle()


def test_each_picture_is_converted_once_and_never_destroyed():
    icon = cached(FakeIcon)("idle")
    icon._assert_icon_handle()
    for image in ("recording", "busy", "idle", "recording", "busy", "idle"):
        icon.set(image)
        assert icon._icon_handle == f"handle-{image}"
    assert icon.converted == ["idle", "recording", "busy"]
    assert icon.destroyed == []
