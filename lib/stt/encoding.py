# TOOLTIP: Починка битой кодировки Vosk на Windows (cp866 -> utf-8)
"""Кодировка строк STT: Vosk на Windows отдаёт кириллицу в cp866.

Функция вызывается на каждом результате распознавания (финал, частичный,
стоп-слова), поэтому вынесена из worker'а отдельно — тот и так на пределе
размера. В `transcription_worker` имя остаётся доступным как `_fix_encoding`
(туда его мокют тесты), так что тесты править не нужно.
"""
import sys


def fix_encoding(text: str) -> str:
    """Чинит битый текст Vosk на Windows (cp866 -> utf-8).

    Корректную кириллицу возвращает как есть.
    """
    if not text or sys.platform != "win32":
        return text
    if any("\u0410" <= ch <= "\u044F" or ch in "\u0401\u0451" for ch in text):
        return text
    try:
        encoded = text.encode("cp866", errors="ignore")
        return encoded.decode("utf-8", errors="ignore")
    except Exception:                        # blind-ok: не роняем строку STT
        return text
