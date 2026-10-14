# TOOLTIP: Разбивка длинного ответа Telegram и снятие инициативных сообщений (сон)
"""Чистые утилиты канала: разбиение текста по `max_len` и гейт «СОН».

Telegram обрезает длинное сообщение молча (лимит 4096), поэтому режем сами по
границам строк: пустые строки выбрасываем, строку длиннее лимита дробим.
`muted` — единая формулировка правила §4.3: пока идёт мероприятие «СОН»,
бот не шлёт инициативу (оповещения, вопросы с кнопками), но отвечает на
собственные сообщения пользователя.
"""

from typing import Callable, Optional

from lib.core.errors import swallowed


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


def muted(check: Optional[Callable[[], bool]], what: str,
          say: Callable[[str], None]) -> bool:
    """Инициативное {what} снято (идёт «СОН»)? Ответы — нет (§4.3).

    `check` — читалка вердикта (None = гейт не подключён, не глушим); сбой
    читалки = «не снято» (fail-open): гейт не цены доставке.
    """
    if check is None:
        return False
    try:
        gated = bool(check())
    except Exception as error:                # вердикт не цена каналу
        swallowed("telegram.mute", error)
        return False
    if gated:
        say(f"[Telegram] «СОН» — {what} снято")
    return gated
