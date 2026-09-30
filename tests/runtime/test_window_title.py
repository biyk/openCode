"""тесты lib/runtime/window_title.py ( ctypes user32 мокаем)."""

from types import SimpleNamespace

import ctypes

from lib.runtime.window_title import foreground_title


class FakeBuf:
    def __init__(self, size):
        self.size = size
        self.value = ""


class FakeUser32:
    def __init__(self, hwnd, title):
        self._hwnd = hwnd
        self._title = title

    def GetForegroundWindow(self):
        return self._hwnd

    def GetWindowTextLengthW(self, hwnd):
        return len(self._title)

    def GetWindowTextW(self, hwnd, buf, size):
        buf.value = self._title
        return len(self._title)


def _patch(monkeypatch, hwnd, title):
    fake = FakeUser32(hwnd, title)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=fake))
    monkeypatch.setattr(ctypes, "create_unicode_buffer",
                        lambda size: FakeBuf(size))


def test_returns_foreground_title(monkeypatch):
    _patch(monkeypatch, hwnd=12345, title="Блокнот — notes.txt")
    assert foreground_title() == "Блокнот — notes.txt"


def test_empty_when_no_window(monkeypatch):
    _patch(monkeypatch, hwnd=0, title="")
    assert foreground_title() == ""


def test_empty_title_yields_empty_string(monkeypatch):
    _patch(monkeypatch, hwnd=999, title="")
    assert foreground_title() == ""
