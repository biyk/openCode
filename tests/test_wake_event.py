"""Юнит-тесты lib/wake_event.py — фиксированный GoogleCalendar без сети.

Проверяют выбор начавшегося события «СОН» (самое позднее начало до
сейчас) и перенос его ЗАВЕРШЕНИЯ на текущий момент без смены начала.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lib.wake_event import WakeEventHandler

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 9, 26, 7, 30, tzinfo=TZ)


def iso(dt: datetime) -> str:
    return dt.isoformat()


class FakeGoogle:
    """Заглушка GoogleCalendar: отдаёт готовые события, помнит patch."""

    def __init__(self, events: list[dict], update_ok: bool = True) -> None:
        self._events = events
        self._update_ok = update_ok
        self.updated: tuple[str, datetime] | None = None

    def list_events_between(self, time_min, time_max, limit=50):
        return [dict(e) for e in self._events]

    def update_event_end(self, event_id: str, new_end: datetime) -> bool:
        self.updated = (event_id, new_end)
        return self._update_ok


def make_event(eid: str, summary: str, start: datetime,
               end: datetime) -> dict:
    return {"id": eid, "summary": summary,
            "start": iso(start), "end": iso(end)}


def test_picks_latest_started_sleep_event():
    """Среди начавшихся «СНов» берётся тот, что начался позже всех."""
    old = make_event("old", "СОН", NOW - timedelta(hours=20),
                     NOW - timedelta(hours=12))
    current = make_event("cur", "СОН", NOW - timedelta(hours=8),
                         NOW + timedelta(hours=1))
    h = WakeEventHandler(google=FakeGoogle([old, current]), now=NOW)
    found = h.find_started_sleep_event()
    assert found and found["id"] == "cur"


def test_ignores_not_started_and_other_titles():
    """Ещё не начавшийся «СОН» и чужие заголовки не подходят."""
    future = make_event("fut", "СОН", NOW + timedelta(hours=1),
                        NOW + timedelta(hours=9))
    run = make_event("run", "Работа", NOW - timedelta(hours=2),
                     NOW + timedelta(hours=2))
    h = WakeEventHandler(google=FakeGoogle([future, run]), now=NOW)
    assert h.find_started_sleep_event() is None


def test_fix_wake_end_shifts_only_end():
    """fix_wake_end меняет только конец (start не трогается)."""
    start = NOW - timedelta(hours=8)
    ev = make_event("cur", "СОН", start, NOW + timedelta(hours=1))
    google = FakeGoogle([ev])
    h = WakeEventHandler(google=google, now=NOW)
    result = h.fix_wake_end()
    assert result and result["id"] == "cur"
    assert google.updated == ("cur", NOW)  # именно update_event_end
    assert result["start"] == iso(start)   # начало как было


def test_fix_wake_end_none_when_no_event():
    """Нет начавшегося «СНА» — None, patch не вызывается."""
    google = FakeGoogle([])
    h = WakeEventHandler(google=google, now=NOW)
    assert h.fix_wake_end() is None
    assert google.updated is None


def test_fix_wake_end_none_when_calendar_fails():
    """Неудачный patch — None (команда сообщит провал)."""
    ev = make_event("cur", "СОН", NOW - timedelta(hours=8),
                    NOW + timedelta(hours=1))
    google = FakeGoogle([ev], update_ok=False)
    h = WakeEventHandler(google=google, now=NOW)
    assert h.fix_wake_end() is None
