"""тесты idle-ветки task_monitor: во время «СОН» вопроса «чем занимаешься?» нет.

Сама проверка «идёт ли сон» — sleep_now, её ветки —
в tests/taskflow/test_task_schedule.py. Здесь — что монитор на idle
не печатает вопрос, не шлёт его в Telegram и не поднимает проверку окна,
а при сбое календаря молчание НЕ включается (fail-open).
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from lib.core.task_monitor import TaskMonitor


def _idle_rows():
    return [{"task_title": "Уборка", "task_time": 10, "start_date": 0,
             "task_uuid": "u-1"}]


def _sheet(rows):
    sheet = MagicMock()
    sheet.read_all_tasks.return_value = rows
    return sheet


def _sleep_event(start_min=-120, end_min=240, summary="СОН"):
    """Событие «СОН», идущее сейчас (началось 2 часа назад, кончится через 4)."""
    base = datetime.now().astimezone()
    return {"summary": summary,
            "start": (base + timedelta(minutes=start_min)).isoformat(),
            "end": (base + timedelta(minutes=end_min)).isoformat()}


def _monitor(mocker, events=None, raise_events=False):
    """Монитор с мок-таблицей (idle) и мок-календарём на events."""
    gcal = MagicMock()
    if raise_events:
        gcal.list_events_between.side_effect = OSError("нет токена")
    else:
        gcal.list_events_between.return_value = events or []
    ask = mocker.MagicMock(return_value=True)
    notify = mocker.MagicMock()
    monitor = TaskMonitor(
        ask=ask, say=mocker.MagicMock(), output=mocker.MagicMock(),
        core=lambda text: text, sheet=_sheet(_idle_rows()),
        handler=MagicMock(), gcal=gcal, notify=notify)
    monitor._rest = MagicMock()
    return monitor, ask, notify


class TestSleepSilencesQuestion:
    def test_running_sleep_skips_question(self, mocker):
        monitor, ask, notify = _monitor(mocker, [_sleep_event()])
        assert monitor.tick() == "sleep"
        ask.assert_not_called()
        notify.assert_not_called()

    def test_running_sleep_skips_rest_check(self, mocker):
        """Окном тоже не занимаемся: пользователь спит, а не отдыхает."""
        monitor, _, _ = _monitor(mocker, [_sleep_event()])
        monitor.tick()
        monitor._rest.check_async.assert_not_called()

    def test_sleep_decision_is_logged(self, mocker):
        monitor, _, _ = _monitor(mocker, [_sleep_event()])
        monitor.tick()
        assert "СОН" in monitor._output.print_info.call_args.args[0]

    def test_finished_sleep_asks_again(self, mocker):
        """«СОН» завершился (конец в прошлом) — вопрос возвращается."""
        monitor, ask, _ = _monitor(
            mocker, [_sleep_event(start_min=-600, end_min=-30)])
        assert monitor.tick() == "idle"
        ask.assert_called_once()

    def test_future_sleep_does_not_silence(self, mocker):
        """Вечерний «СОН» ещё не начался — спрашиваем как обычно."""
        ev = _sleep_event(start_min=120, end_min=480)
        monitor, ask, _ = _monitor(mocker, [ev])
        assert monitor.tick() == "idle"
        ask.assert_called_once()

    def test_calendar_failure_keeps_question(self, mocker):
        """Сбой чтения календаря — fail-open: вопрос задаётся, молчание нет."""
        monitor, ask, _ = _monitor(mocker, raise_events=True)
        assert monitor.tick() == "idle"
        ask.assert_called_once()

    def test_busy_task_untouched_by_sleep(self, mocker):
        """Задача запущена — idle-ветка (и сон) вообще не рассматриваются."""
        sheet = _sheet([{"task_title": "Работа", "task_time": 10,
                         "start_date": 1_700_000_000_000, "task_uuid": "u-1"}])
        gcal = MagicMock()
        gcal.list_events_between.return_value = [_sleep_event()]
        monitor = TaskMonitor(ask=mocker.MagicMock(return_value=True),
                              say=mocker.MagicMock(), output=mocker.MagicMock(),
                              sheet=sheet, handler=MagicMock(), gcal=gcal)
        assert monitor.tick() == "busy"
        gcal.list_events_between.assert_not_called()
