# TOOLTIP: Тесты оповещения о переработке: озвучка/дубль в Telegram, повтор каждый такт
"""Тесты `lib/core/overtime.py`.

Тестируем:
- срабатывание строго на пороге `task_time × множителя` и тишину в норме;
- текст оповещения (название + факт + время/план) в голосе, консоли и Telegram;
- это сообщение (`say`), а не вопрос (`ask`): ответ от пользователя не нужен;
- ПОКА задача в переработке оповещение повторяется на каждый такт монитора
  (remind=0 по умолчанию); `remind_min > 0` ограничивает частоту повторов;
- снятие/рестарт задачи разрешает оповестить заново.

Детекцию не мокнем: строку таблицы гоняем через `evaluate` (реальный
`SheetCheck`), а «сколько идёт задача» задаем временем `now_ms` относительно
`start_date` — так проверяется и `find_overtime`, и нотифайер вместе.
"""

from lib.core.overtime import OvertimeNotifier
from lib.taskflow.task_check import evaluate

START = 1_700_000_000_000
MIN = 60_000


def _sheet(uuid="u-1", title="Задача", plan=120, start=START):
    """Реальный снимок таблицы с одной задачей (start=0 — не запущена)."""
    return evaluate([{"task_uuid": uuid, "task_title": title,
                      "task_time": plan, "start_date": start}])


def _notifier(mocker, notify=None, multiplier=1.2, remind_min=None):
    """Оповеститель с моками say/output/notify; дефолт remind — из модуля."""
    say = mocker.MagicMock(name="say")
    output = mocker.MagicMock(name="output")
    ask = mocker.MagicMock(name="ask")      # ask не должен вызываться
    kwargs = {} if remind_min is None else {"remind_min": remind_min}
    ot = OvertimeNotifier(say=say, output=output, notify=notify,
                          multiplier=multiplier, **kwargs)
    return ot, say, output, ask


class TestAnnounce:
    """Одно оповещение: когда и чем."""

    def test_silent_within_norm(self, mocker):
        ot, say, _out, _ask = _notifier(mocker)
        # план 120, множитель 1.2 -> порог 144; 100 минут — ещё в норме
        assert ot.check(_sheet(), now_ms=START + 100 * MIN) == 0
        say.assert_not_called()

    def test_announces_over_threshold(self, mocker):
        telegram = mocker.MagicMock(name="notify")
        ot, say, out, _ask = _notifier(mocker, notify=telegram)
        now = START + 169 * MIN
        assert ot.check(_sheet(), now_ms=now) == 1
        spoken = say.call_args_list[0][0][0]
        assert "Задача" in spoken
        assert "169" in spoken and "120" in spoken   # факт и норма в тексте
        out.print_info.assert_called_once()
        telegram.assert_called_once_with(spoken)     # тот же текст в чат

    def test_uses_say_not_ask(self, mocker):
        ot, say, _out, ask = _notifier(mocker)
        ot.check(_sheet(), now_ms=START + 200 * MIN)
        say.assert_called()
        ask.assert_not_called()


class TestRepeat:
    """Пока задача в переработке — оповещение не глохнет после первого раза."""

    def test_repeats_every_check_by_default(self, mocker):
        # remind=0 (дефолт): каждый такт монитора = повтор (интервал = 10 мин)
        ot, say, _out, _ask = _notifier(mocker)
        now = START + 169 * MIN
        assert ot.check(_sheet(), now_ms=now) == 1
        assert ot.check(_sheet(), now_ms=now + MIN) == 1
        assert say.call_count == 2

    def test_remind_window_suppresses_early_repeat(self, mocker):
        ot, say, _out, _ask = _notifier(mocker, remind_min=15.0)
        now = START + 169 * MIN
        assert ot.check(_sheet(), now_ms=now) == 1
        assert ot.check(_sheet(), now_ms=now + MIN) == 0        # 1 мин < окна
        assert ot.check(_sheet(), now_ms=now + 16 * MIN) == 1   # ≥ окна — снова
        assert say.call_count == 2

    def test_restarts_after_task_stops(self, mocker):
        # Сняли задачу (start=0 -> не running) и запустили заново: снова 1
        ot, say, _out, _ask = _notifier(mocker)
        now = START + 169 * MIN
        assert ot.check(_sheet(), now_ms=now) == 1
        assert ot.check(_sheet(start=0), now_ms=now) == 0
        assert ot.check(_sheet(), now_ms=now + MIN) == 1        # ре-старт
        assert say.call_count == 2


class TestNoTelegramSink:
    """Бот не поднят — озвучка работает, Telegram просто не трогаем."""

    def test_notify_none_is_ok(self, mocker):
        ot, say, _out, _ask = _notifier(mocker, notify=None)
        assert ot.check(_sheet(), now_ms=START + 169 * MIN) == 1
        say.assert_called_once()
