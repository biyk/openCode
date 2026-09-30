"""тесты offer-ветки idle в task_monitor: время-зависимое предложение + кнопки."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from lib.core.task_monitor import PROPOSE_PREFIX, QUESTION_IDLE, TaskMonitor

UA = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
UB = "11111111-2222-3333-4444-555555555555"


def _rows():
    return [{"task_title": "А", "task_uuid": UA, "start_date": 0,
             "task_time": 30},
            {"task_title": "Б", "task_uuid": UB, "start_date": 0,
             "task_time": 30}]


def _sheet(rows):
    sheet = MagicMock()
    sheet.read_all_tasks.return_value = rows
    return sheet


def _event(uuid, start_min, end_min, summary="Задача", color=""):
    base = datetime.now().astimezone()
    return {"id": uuid, "summary": summary, "colorId": color,
            "description": uuid,
            "start": (base + timedelta(minutes=start_min)).isoformat(),
            "end": (base + timedelta(minutes=end_min)).isoformat()}


def _monitor(mocker, events=None, offer=None, notify=None, accepted=True):
    ask = mocker.MagicMock(return_value=accepted)
    gcal = mocker.MagicMock() if events is not None else None
    if gcal is not None:
        gcal.list_events_between.return_value = events
    monitor = TaskMonitor(
        ask=ask, say=mocker.MagicMock(), output=mocker.MagicMock(),
        core=lambda text: text, sheet=_sheet(_rows()), handler=MagicMock(),
        gcal=gcal, offer=offer, notify=notify)
    return monitor, ask


class TestIdleOfferPath:
    def test_running_task_voiced_and_buttons_offered(self, mocker):
        """Идущая сейчас «А» в голосовом вопросе; «А»/«Б» — кнопками в чат."""
        offer = mocker.MagicMock()
        notify = mocker.MagicMock()
        events = [_event(UA, -5, 25), _event(UB, 40, 60)]
        monitor, ask = _monitor(mocker, events, offer=offer, notify=notify)
        assert monitor.tick() == "idle"
        question = ask.call_args.args[0]
        assert f"{PROPOSE_PREFIX} А" in question
        offer.assert_called_once_with(QUESTION_IDLE, ["А", "Б"])
        notify.assert_not_called()

    def test_no_events_falls_back_to_plain_notify(self, mocker):
        """Без календаря (gcal=None) — откат: вопрос по таблице, текста в чат."""
        offer = mocker.MagicMock()
        notify = mocker.MagicMock()
        monitor, ask = _monitor(mocker, None, offer=offer, notify=notify)
        assert monitor.tick() == "idle"
        assert f"{PROPOSE_PREFIX} А" in ask.call_args.args[0]
        offer.assert_not_called()
        notify.assert_called_once()

    def test_events_read_error_degrades_to_fallback(self, mocker):
        """Сбой чтения календаря не роняет цикл — тот же откат к таблице."""
        notify = mocker.MagicMock()
        gcal_events = MagicMock()
        gcal_events.list_events_between.side_effect = OSError("нет токена")
        monitor = TaskMonitor(
            ask=mocker.MagicMock(return_value=True), say=mocker.MagicMock(),
            output=mocker.MagicMock(), core=lambda t: t, sheet=_sheet(_rows()),
            handler=MagicMock(), gcal=gcal_events, notify=notify)
        assert monitor.tick() == "idle"
        notify.assert_called_once()

    def test_deferred_when_ask_rejected(self, mocker):
        offer = mocker.MagicMock()
        events = [_event(UA, -5, 25)]
        monitor, _ = _monitor(mocker, events, offer=offer, accepted=False)
        assert monitor.tick() == "deferred"
        offer.assert_not_called()
