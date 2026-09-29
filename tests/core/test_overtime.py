"""Тесты оповещения о переработке (lib/core/overtime.py).

Проверяем главное, из-за чего фичу калечили: переработка ОЗВУЧИВАЕТСЯ и
ВЫВОДИТСЯ (плюс дубль в Telegram) и при этом НЕ ждёт ответа (не `ask`), а
на одну запущенную задачу предупреждение уходит ОДИН раз.
"""

from lib.core.overtime import OvertimeNotifier
from lib.taskflow.task_check import evaluate

MIN = 60_000
START = 1_700_000_000_000


def _sheet(plan=93, start=None, title="Обед", uuid="u-1"):
    """Лист с одной задачей в заданном состоянии (для find_overtime)."""
    return evaluate([{"task_title": title, "task_time": plan,
                      "start_date": start if start is not None else START,
                      "task_uuid": uuid}])


def _notifier(mocker, notify=None, multiplier=1.2):
    say = mocker.MagicMock()
    output = mocker.MagicMock()
    sink = notify if notify is not None else mocker.MagicMock()
    return OvertimeNotifier(say=say, output=output, notify=sink,
                            multiplier=multiplier), say, output, sink


class TestAnnounce:
    """Переработка: озвучить + вывести + продублировать, без ожидания."""

    def test_overdue_announces_voice_print_telegram(self, mocker):
        ot, say, output, sink = _notifier(mocker)
        now = START + 169 * MIN
        assert ot.check(_sheet(), now_ms=now) == 1
        message = say.call_args.args[0]
        assert "Обед" in message and "169" in message and "93" in message
        assert "Всё ли в порядке" in message
        output.print_info.assert_called_once()
        sink.assert_called_once_with(message)      # тот же текст в Telegram

    def test_uses_say_not_ask(self, mocker):
        """Оповещение не открывает ожидание ответа: у нотифайера нет ask."""
        ot, _say, _out, _sink = _notifier(mocker)
        assert not hasattr(ot, "_ask")
        ot.check(_sheet(), now_ms=START + 169 * MIN)
        # say вызван ровно раз и это просто озвучка (см. предыдущий тест).
        assert _say.call_count == 1

    def test_within_norm_stays_silent(self, mocker):
        ot, say, output, sink = _notifier(mocker)
        assert ot.check(_sheet(), now_ms=START + 100 * MIN) == 0
        say.assert_not_called()
        output.print_info.assert_not_called()
        sink.assert_not_called()


class TestOneShot:
    """Разовость: на одну запущенную задачу — одно предупреждение."""

    def test_second_check_does_not_repeat(self, mocker):
        ot, say, _out, _sink = _notifier(mocker)
        now = START + 169 * MIN
        assert ot.check(_sheet(), now_ms=now) == 1
        assert ot.check(_sheet(), now_ms=now + MIN) == 0   # та же задача
        assert say.call_count == 1

    def test_restarts_after_task_stops(self, mocker):
        """Задача упала из running и снова запустилась — предупреждение снова."""
        ot, say, _out, _sink = _notifier(mocker)
        now = START + 169 * MIN
        assert ot.check(_sheet(uuid="u-1"), now_ms=now) == 1
        assert ot.check(_sheet(uuid="u-1", start=0), now_ms=now) == 0  # idle
        assert ot.check(_sheet(uuid="u-1"), now_ms=now) == 1           # ре-старт
        assert say.call_count == 2


class TestNoTelegramSink:
    """Без Telegram-канала (бот не поднят) озвучка и вывод всё равно идут."""

    def test_none_notify_still_speaks_and_prints(self, mocker):
        ot = OvertimeNotifier(say=mocker.MagicMock(),
                              output=mocker.MagicMock(), notify=None)
        assert ot.check(_sheet(), now_ms=START + 169 * MIN) == 1
        ot._say.assert_called_once()
        ot._output.print_info.assert_called_once()
