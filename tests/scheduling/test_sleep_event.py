"""Юнит-тесты lib/sleep_event.py — фиксированный GoogleCalendar без сети.

Проверяют выбор события «СОН» (идущее/скорое, без завершившихся и
посторонних заголовков), перенос его начала на текущий момент и
побочный сдвиг утреннего cron-задания на now + 7ч30.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from lib.scheduling import cron_edit
from lib.sleep_event import (
    WAKE_JOB_ID,
    SleepEventHandler,
    shift_wake_job,
)

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 9, 25, 23, 30, tzinfo=TZ)


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

    def update_event_start(self, event_id: str, new_start: datetime) -> bool:
        self.updated = (event_id, new_start)
        return self._update_ok


def make_event(eid: str, summary: str, start: datetime,
               end: datetime) -> dict:
    return {"id": eid, "summary": summary,
            "start": iso(start), "end": iso(end)}


def test_finds_event_already_running():
    """Событие, идущее сейчас (началось в прошлом), — кандидат."""
    ev = make_event("a", "СОН", NOW - timedelta(hours=1),
                    NOW + timedelta(hours=8))
    other = make_event("b", "Ужин", NOW - timedelta(minutes=10),
                       NOW + timedelta(minutes=20))
    h = SleepEventHandler(google=FakeGoogle([other, ev]), now=NOW)
    found = h.find_sleep_event()
    assert found and found["id"] == "a"


def test_skips_finished_events_and_other_titles():
    """Завершившийся «СОН» и чужие заголовки не подходят."""
    old = make_event("old", "СОН", NOW - timedelta(hours=10),
                     NOW - timedelta(hours=1))
    walk = make_event("walk", "Прогулка с Соней", NOW + timedelta(minutes=5),
                      NOW + timedelta(minutes=30))
    h = SleepEventHandler(google=FakeGoogle([old, walk]), now=NOW)
    assert h.find_sleep_event() is None


def test_picks_earliest_upcoming():
    """Из будущих «СОНов» берётся ближайшее по началу."""
    e1 = make_event("late", "СОН", NOW + timedelta(hours=2),
                    NOW + timedelta(hours=10))
    e2 = make_event("soon", "сон", NOW + timedelta(minutes=10),
                    NOW + timedelta(hours=9))
    h = SleepEventHandler(google=FakeGoogle([e1, e2]), now=NOW)
    found = h.find_sleep_event()
    assert found and found["id"] == "soon"


def test_fix_sleep_start_shifts_start_to_now():
    """fix_sleep_start переносит начало на сейчас и возвращает событие."""
    ev = make_event("a", "СОН", NOW + timedelta(minutes=30),
                    NOW + timedelta(hours=9))
    google = FakeGoogle([ev])
    h = SleepEventHandler(google=google, now=NOW)
    result = h.fix_sleep_start()
    assert result and result["id"] == "a"
    assert google.updated == ("a", NOW)


def test_fix_sleep_start_none_when_calendar_fails():
    """Неудачный patch — None (команда сообщит провал)."""
    ev = make_event("a", "СОН", NOW + timedelta(minutes=30),
                    NOW + timedelta(hours=9))
    google = FakeGoogle([ev], update_ok=False)
    h = SleepEventHandler(google=google, now=NOW)
    assert h.fix_sleep_start() is None


def _write_crontab(tmp_path, job_id=WAKE_JOB_ID) -> str:
    path = str(tmp_path / "crontab.json")
    with open(path, "w", encoding="utf-8") as file:
        json.dump({"jobs": [{"id": job_id, "schedule": "15 9 * * *",
                             "script": "wake_video_and_volume.ps1"}]},
                  file, ensure_ascii=False, indent=4)
    return path


def test_shift_wake_job_moves_to_now_plus_7h30(tmp_path, monkeypatch):
    """«я спать» переносит wake_video_and_volume на сейчас + 7ч30."""
    path = _write_crontab(tmp_path)
    monkeypatch.setattr(cron_edit, "CRONTAB_FILE", path)
    now = datetime(2026, 9, 27, 23, 40, tzinfo=TZ)
    shift_wake_job(now)
    with open(path, encoding="utf-8") as file:
        job = json.load(file)["jobs"][0]
    assert job["schedule"] == "10 7 * * *"  # 23:40 + 7:30 → 07:10


def test_shift_wake_job_missing_job_is_noop(tmp_path, monkeypatch):
    """Нет задания в расписании — файл не тронут, исключения нет."""
    path = _write_crontab(tmp_path, job_id="other")
    monkeypatch.setattr(cron_edit, "CRONTAB_FILE", path)
    shift_wake_job(datetime(2026, 9, 27, 23, 40, tzinfo=TZ))
    with open(path, encoding="utf-8") as file:
        job = json.load(file)["jobs"][0]
    assert job["schedule"] == "15 9 * * *"
