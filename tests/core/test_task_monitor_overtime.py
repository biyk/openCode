"""Тесты связки task_monitor ↔ оповещение о переработке.

Отдельно от test_task_monitor.py (тот упирается в лимит строк): здесь только
то, что фоновый цикл реально дёргает OvertimeNotifier на каждый снимок таблицы
и что фабрика собирает его по секции task_monitor (в т.ч. дубль в Telegram).
"""

from unittest.mock import MagicMock

from lib.core.overtime import OvertimeNotifier
from lib.core.task_monitor import TaskMonitor, start_task_monitor
from lib.core.tuning import TASK_OVERTIME_MULTIPLIER

MIN = 60_000
START = 1_700_000_000_000


def _row(title="Обед", plan=93, start=None, uuid="u-1"):
    return {"task_title": title, "task_time": plan,
            "start_date": start if start is not None else START,
            "task_uuid": uuid}


def _sheet(rows):
    sheet = MagicMock()
    sheet.read_all_tasks.return_value = rows
    return sheet


def _monitor(overtime, rows):
    return TaskMonitor(ask=MagicMock(), say=MagicMock(),
                       output=MagicMock(), sheet=_sheet(rows),
                       handler=MagicMock(), overtime=overtime)


class TestTickWiring:
    """Каждый такт монитора прогоняет проверку переработки на снимке таблицы."""

    def test_tick_calls_overtime_with_check(self, mocker):
        overtime = mocker.MagicMock()
        overtime.check.return_value = 1
        monitor = _monitor(overtime, [_row()])
        assert monitor.tick() == "busy"        # задача запущена — не idle
        overtime.check.assert_called_once()
        # В check передали SheetCheck с этой самой задачей.
        passed = overtime.check.call_args.args[0]
        assert [t.uuid for t in passed.running] == ["u-1"]

    def test_tick_without_overtime_is_unaffected(self):
        """Без нотифайера (секция выключена) цикл работает как раньше."""
        monitor = _monitor(None, [_row(start=0)])
        assert monitor.tick() == "idle"

    def test_overtime_runs_even_before_idle_question(self, mocker):
        """Проверка переработки не зависит от того, был бы вопрос в idle."""
        overtime = mocker.MagicMock()
        monitor = _monitor(overtime, [_row(start=0)])   # idle-снимок
        monitor.tick()
        overtime.check.assert_called_once()


class TestFactory:
    """Сборка OvertimeNotifier по секции task_monitor и проброс notify."""

    def _worker(self, config):
        worker = MagicMock()
        worker._matcher.get_task_monitor_config.return_value = config
        worker._matcher.get_fun_holes_config.return_value = {}
        worker._matcher.core_phrase.side_effect = lambda text: text
        return worker

    def test_default_builds_notifier(self, mocker):
        mocker.patch.object(TaskMonitor, "start")
        monitor = start_task_monitor(self._worker({"enabled": True}),
                                     MagicMock())
        assert isinstance(monitor._overtime, OvertimeNotifier)
        assert monitor._overtime._multiplier == TASK_OVERTIME_MULTIPLIER

    def test_disabled_section_drops_notifier(self, mocker):
        mocker.patch.object(TaskMonitor, "start")
        monitor = start_task_monitor(
            self._worker({"enabled": True, "overtime_enabled": False}),
            MagicMock())
        assert monitor._overtime is None

    def test_threads_notify_and_multiplier(self, mocker):
        mocker.patch.object(TaskMonitor, "start")
        sink = MagicMock()
        monitor = start_task_monitor(
            self._worker({"enabled": True, "overtime_multiplier": 1.5}),
            MagicMock(), notify=sink)
        assert monitor._overtime._notify is sink
        assert monitor._overtime._multiplier == 1.5
