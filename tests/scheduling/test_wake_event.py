"""Юнит-тесты lib/wake_event.py — фиксированный GoogleCalendar без сети.

Проверяют выбор начавшегося события «СОН» (самое позднее начало до
сейчас), перенос его ЗАВЕРШЕНИЯ на текущий момент без смены начала и
засчёт задачи «Пробуждение» по ✅ (mark_task_done — заглушка).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import lib.wake_event as wake_module
from lib.wake_event import WAKE_TASK_UUID, WakeEventHandler

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


class Recorded:
    """Заглушка mark_task_done: помнит uuid и отдаёт готовый результат."""

    def __init__(self, result=None, error=None) -> None:
        self.calls: list[str] = []
        self.result = result if result is not None else {
            "ok": True, "title": "Пробуждение", "time_spent": 3, "money": 1.5}
        self.error = error

    def __call__(self, task_uuid, now=None, **kwargs) -> dict:
        self.calls.append(task_uuid)
        if self.error:
            raise self.error
        return self.result


def patch_done(monkeypatch, recorded: Recorded) -> Recorded:
    monkeypatch.setattr(wake_module, "mark_task_done", recorded)
    return recorded


def test_count_wake_task_marks_wake_uuid(monkeypatch, capsys):
    """✅ по задаче «Пробуждение»: вызов со стабильным uuid, код True."""
    recorded = patch_done(monkeypatch, Recorded())
    assert wake_module.count_wake_task(NOW) is True
    assert recorded.calls == [WAKE_TASK_UUID]
    assert "Пробуждение" in capsys.readouterr().out


def test_count_wake_task_swallows_errors(monkeypatch, capsys):
    """Сбой Google/запущенная задача — False и сообщение, без исключения."""
    patch_done(monkeypatch,
               Recorded(error=RuntimeError("нет токена")))
    assert wake_module.count_wake_task(NOW) is False
    assert "не засчитано" in capsys.readouterr().out

    patch_done(monkeypatch,
               Recorded(result={"ok": False, "error": "нет строки"}))
    assert wake_module.count_wake_task(NOW) is False
    assert "нет строки" in capsys.readouterr().out

    patch_done(monkeypatch, Recorded(result={"ok": True, "skipped": True,
                                             "title": "Пробуждение"}))
    assert wake_module.count_wake_task(NOW) is True
    assert "уже засчитана" in capsys.readouterr().out


def run_main(monkeypatch, events, recorded):
    """CLI команды на фейковом календаре и фейковом засчёте задачи."""
    patch_done(monkeypatch, recorded)
    handler = WakeEventHandler(google=FakeGoogle(events), now=NOW)
    monkeypatch.setattr(wake_module, "WakeEventHandler", lambda: handler)
    return wake_module._main([])


def test_main_counts_task_even_without_sleep_event(monkeypatch, capsys):
    """«СОН» не найден, но задача засчитана — команда считается выполненной."""
    recorded = Recorded()
    code = run_main(monkeypatch, [], recorded)
    assert code == 0
    assert recorded.calls == [WAKE_TASK_UUID]
    assert "не найдено" in capsys.readouterr().out


def test_main_fails_when_neither_action_worked(monkeypatch):
    """Ни сон не найден, ни задача не засчитана — код 1."""
    assert run_main(monkeypatch, [], Recorded(
        error=RuntimeError("нет сети"))) == 1
