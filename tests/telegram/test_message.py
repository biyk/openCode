# TOOLTIP: Тесты утилит канала Telegram: разбивка ответа и снятие инициативы
"""Тесты разбиения длинного ответа Telegram (`lib/telegram/message.py`).

Прямые тесты чистой функции: `tests/telegram/test_bot.py` проверяет те же
границы через `bot.chunks`, но только с дефолтным `max_len` конфига.
`muted` — то же правило §4.3 (нет инициативы во время «СОН») в отрыве от бота.
"""
from unittest.mock import MagicMock

import lib.telegram.message as message_mod
from lib.telegram.message import muted, split_chunks


def _boom() -> bool:
    """Читалка вердикта, которая падает (нет календаря/сети)."""
    raise OSError("нет токена")


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


class TestMuted:
    """Инициатива снимается только по вердикту «СОН» (ответы — нет)."""

    def test_no_gate_means_no_mute(self):
        say = MagicMock()
        assert muted(None, "уведомление", say) is False
        say.assert_not_called()

    def test_sleeping_mutes_and_logs(self):
        say = MagicMock()
        assert muted(lambda: True, "уведомление", say) is True
        assert "СОН" in say.call_args.args[0]
        assert "уведомление" in say.call_args.args[0]

    def test_awake_passes(self):
        say = MagicMock()
        assert muted(lambda: False, "предложение", say) is False
        say.assert_not_called()

    def test_gate_failure_does_not_mute(self, mocker):
        """Сбой читалки вердикта — канал жив: гейт не цены доставке."""
        swallowed = mocker.patch.object(message_mod, "swallowed")
        assert muted(_boom, "уведомление", MagicMock()) is False
        swallowed.assert_called_once()
