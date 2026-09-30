"""тесты idle-ветки task_monitor: делегирование проверки окна в RestWatch.

Сама логика опроса модели — в test_rest_watch.py. Здесь — что monitor на idle
передаёт проверку окна фоновому RestWatch (не блокируя цикл) и не трогает сеть
без примитивов, а на busy вообще не запускает проверку.
"""

from unittest.mock import MagicMock

from lib.core.task_monitor import TaskMonitor


def _sheet(rows):
    sheet = MagicMock()
    sheet.read_all_tasks.return_value = rows
    return sheet


def _idle_rows():
    return [{"task_title": "Уборка", "task_time": 10, "start_date": 0,
             "task_uuid": "u-1"}]


def _monitor(mocker, rows=None):
    return TaskMonitor(ask=mocker.MagicMock(return_value=True),
                       say=mocker.MagicMock(), output=mocker.MagicMock(),
                       core=lambda text: text,
                       sheet=_sheet(rows or _idle_rows()),
                       handler=mocker.MagicMock())


class TestIdleDispatchesRestWatch:
    def test_idle_dispatches_rest_check(self, mocker):
        monitor = _monitor(mocker)
        monitor._rest = MagicMock()
        assert monitor.tick() == "idle"
        monitor._rest.check_async.assert_called_once_with()

    def test_rest_check_dispatched_before_question(self, mocker):
        """Окно уходит в фон до вопроса — зависшая модель не задержит вопрос."""
        monitor = _monitor(mocker)
        order = []
        monitor._rest = MagicMock()
        monitor._rest.check_async.side_effect = lambda: order.append("rest")
        monitor._ask = lambda *a, **k: (order.append("ask") or True)
        monitor.tick()
        assert order == ["rest", "ask"]

    def test_busy_does_not_dispatch(self, mocker):
        started = 1_700_000_000_000
        monitor = _monitor(
            mocker, [{"task_title": "Работа", "task_time": 10,
                      "start_date": started, "task_uuid": "u-1"}])
        monitor._rest = MagicMock()
        assert monitor.tick() == "busy"
        monitor._rest.check_async.assert_not_called()

    def test_disabled_rest_watch_touches_nothing(self, mocker):
        """Без примитивов (дефолт) idle не поднимает поток и не печатает."""
        monitor = _monitor(mocker)          # title_fn/classify_fn не заданы
        assert monitor._rest.enabled is False
        assert monitor.tick() == "idle"
        monitor._output.print_info.assert_not_called()
