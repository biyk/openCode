"""Тесты разбиения длинного ответа Telegram (`lib/telegram/message.py`).

Прямые тесты чистой функции: `tests/telegram/test_bot.py` проверяет те же
границы через `bot.chunks`, но только с дефолтным `max_len` конфига.
"""
from lib.telegram.message import split_chunks


def test_keeps_line_boundaries():
    assert split_chunks("ab\ncd\nefghijklmnop", 10) == [
        "ab\ncd", "efghijklmn", "op"]


def test_blank_lines_are_dropped():
    assert split_chunks("\n  \n", 10) == []
    assert split_chunks("Готово", 10) == ["Готово"]


def test_line_longer_than_limit_is_divided():
    assert split_chunks("Выполнено: stop", 10) == ["Выполнено:", " stop"]


def test_limit_below_one_does_not_divide_by_zero():
    """limit <= 0 → 1: бесконечный цикл или пустые части тут ни к чему."""
    parts = split_chunks("abc", 0)
    assert "".join(parts) == "abc"
    assert all(p for p in parts)
