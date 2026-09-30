"""Заголовок переднего (активного) окна Windows через user32, без pywin32.

``GetForegroundWindow`` даёт hwnd активного окна, ``GetWindowTextLengthW`` +
``GetWindowTextW`` вытаскивают его заголовок в широкий буфер. Всё на ctypes —
как в остальном ``lib/runtime`` (COM/WIN-API напрямую).
"""

import ctypes


def foreground_title() -> str:
    """Заголовок активного окна; пустая строка, если окна/заголовка нет."""
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value or ""
