# TOOLTIP: Тесты гейта «СОН»: липкий вердикт, кэш без сети, строка панели
"""Тесты `lib/core/sleep_gate.py` — единого вердикта «идёт мероприятие СОН».

Главное — липкость: сбой календаря (и пустой ответ) НЕ переключает «спим» на
«не спим», иначе инициативные сообщения вернулись бы посреди ночи (§4.3). На
свежем процессе вердикта нет — там по-прежнему fail-open: молчание не
включится из-за сломанного календаря. Кэш читают дёшево и без сети.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import lib.core.sleep_gate as gate
from lib.core.sleep_gate import (check_sleeping, is_sleeping, set_sleeping,
                                 today_events)


def _gcal(events=None, error=None):
    """Мок-календарь: отдаёт события или бросает ошибку."""
    cal = MagicMock()
    if error is not None:
        cal.list_events_between.side_effect = error
    else:
        cal.list_events_between.return_value = events or []
    return cal


def _sleep_event(start_min=-120, end_min=240, summary="СОН"):
    """Событие «СОН», идущее сейчас (началось 2 часа назад, кончится через 4)."""
    base = datetime.now().astimezone()
    return {"summary": summary,
            "start": (base + timedelta(minutes=start_min)).isoformat(),
            "end": (base + timedelta(minutes=end_min)).isoformat()}


def _work_event():
    """Обычное идущее событие — сна в нём нет."""
    return _sleep_event(summary="Работа")


class TestVerdict:
    def test_sleep_event_sets_verdict(self):
        assert check_sleeping(_gcal([_sleep_event()])) is True
        assert is_sleeping() is True

    def test_no_sleep_event_clears_verdict(self):
        set_sleeping(True)
        assert check_sleeping(_gcal([_work_event()])) is False
        assert is_sleeping() is False

    def test_finished_sleep_unsilences(self):
        """«СОН» завершился (конец в прошлом) — вердикт снова «не спим»."""
        set_sleeping(True)
        event = _sleep_event(start_min=-600, end_min=-30)
        assert check_sleeping(_gcal([event])) is False

    def test_future_sleep_is_not_sleeping(self):
        event = _sleep_event(start_min=120, end_min=480)
        assert check_sleeping(_gcal([event])) is False


class TestStickyOnFailure:
    """Сбой календаря держит прошлый вердикт — это суть гейта."""

    def test_failure_keeps_sleeping(self):
        """Ночью сеть/токен отвалились — молчание НЕ должно сняться."""
        set_sleeping(True)
        assert check_sleeping(_gcal(error=OSError("нет токена"))) is True
        assert is_sleeping() is True

    def test_failure_on_boot_is_fail_open(self):
        """Вердикта ещё нет (свежий процесс) — сбой не выдумывает сон."""
        assert check_sleeping(_gcal(error=OSError("нет сети"))) is False

    def test_empty_calendar_counts_as_failure(self):
        """Пустой список — тот же сбой: пересчитывать «не спим» нельзя."""
        set_sleeping(True)
        assert check_sleeping(_gcal([])) is True

    def test_events_are_read_for_today(self):
        cal = _gcal([_sleep_event()])
        check_sleeping(cal)
        start, end = cal.list_events_between.call_args.args
        assert start.hour == 0 and start.minute == 0
        assert (end - start).days == 1

    def test_injected_calendar_is_used(self, mocker):
        """Свой календарь не должен рождать реальный GoogleCalendar."""
        build = mocker.patch.object(gate, "calendar",
                                    side_effect=AssertionError("сеть лишняя"))
        check_sleeping(_gcal([_sleep_event()]))
        build.assert_not_called()

    def test_today_events_returns_list_on_failure(self):
        assert today_events(_gcal(error=OSError("нет токена"))) == []


class TestPanel:
    def test_verdict_shown_in_services_panel(self, mocker):
        """Строка «Сон» в панели: видно, почему ассистент молчит."""
        report = mocker.patch.object(gate.registry, "report")
        check_sleeping(_gcal([_sleep_event()]))
        sid, name, state, detail = report.call_args.args
        assert (sid, name) == (gate.SLEEP_STATUS, "Сон")
        assert state == gate.registry.IDLE and "СОН" in detail

    def test_awake_verdict_is_working(self, mocker):
        """Не спим — зелёная строка, а не «сервис выключен»."""
        report = mocker.patch.object(gate.registry, "report")
        check_sleeping(_gcal([_work_event()]))
        assert report.call_args.args[2] == gate.registry.WORKING

    def test_no_startup_probe_function(self):
        """Сон при запуске не проверяют: вердикт считает только цикл."""
        assert not hasattr(gate, "warm")
