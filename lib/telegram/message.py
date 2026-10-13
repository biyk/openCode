# TOOLTIP: Разбивка длинного ответа Telegram по лимиту длины сообщения
"""Чистая утилита разбиения текста: без сети и состояния — только `max_len`.

Telegram обрезает длинное сообщение молча (лимит 4096), поэтому режем сами по
границам строк: пустые строки выбрасываем, строку длиннее лимита дробим.
"""


def split_chunks(text: str, limit: int) -> list[str]:
    """Части текста не длиннее `limit`, сохраняя границы строк."""
    size = max(1, int(limit))
    lines = [line for line in str(text).splitlines() if line.strip()]
    parts: list[str] = []
    current = ""
    for line in lines:
        while len(line) > size:               # одна строка длиннее лимита
            if current:                       # сначала дописываем накопленное
                parts.append(current)
                current = ""
            parts.append(line[:size])
            line = line[size:]
        glued = f"{current}\n{line}" if current else line
        if len(glued) > size:
            parts.append(current)
            current = line
        else:
            current = glued
    if current:
        parts.append(current)
    return parts
