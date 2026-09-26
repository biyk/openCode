"""Интеграция команды «я проснулся»: перенос из окна сна + автозаполнение дня.

Проверяет WakeEventHandler.replan_day целиком на фейковом календаре и
фейковом листе задач (без сети): события, попавшие в окно сна, сдвигаются
на окна после пробуждения, а остаток дня заполняется задачами из
real_life_tasks. Мутации Таблиц не происходит (fill_calendar только читает).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import lib.wake_event as wake_module
from lib.wake_event import WakeEventHandler

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 9, 26, 8, 0, tzinfo=TZ)
NOW_MS = int(NOW.timestamp() * 1000)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def event(eid, summary, start, end, description=""):
    return {"id": eid, "summary": summary, "start": iso(start),
            "end": iso(end), "description": description}


def task(title, uuid, minutes, sort=1):
    return {"task_title": title, "task_uuid": uuid, "task_time": minutes,
            "task_sort": sort, "break_multiplier": 0,
            "task_date": NOW_MS - 1000, "excludes": ""}


class FakeGoogle:
    """Заглушка GoogleCalendar: отдаёт события дня, помнит move/insert."""

    def __init__(self, events):
        self._events = events
        self.moved: list[tuple] = []
        self.created: list[tuple] = []

    def list_events_between(self, time_min, time_max, limit=50):
        return [dict(e) for e in self._events]

    def move_event(self, event_id, new_start, new_end):
        self.moved.append((event_id, new_start, new_end))
        return True

    def create_task_event(self, summary, description, start, end):
        self.created.append((summary, description, start, end))
        return "new-" + description


class FakeSheet:
    """Заглушка RealLifeSheet: только чтение листа задач."""

    def __init__(self, tasks):
        self._tasks = tasks

    def read_all_tasks(self):
        return list(self._tasks)


def make_handler(events, tasks, monkeypatch):
    """Хендлер на фейковом календаре; RealLifeSheet подменён в модуле."""
    google = FakeGoogle(events)
    monkeypatch.setattr(wake_module, "RealLifeSheet",
                        lambda gcal: FakeSheet(tasks))
    return WakeEventHandler(google=google, now=NOW), google


def test_replan_day_shifts_sleep_then_fills(monkeypatch):
    """Задача из окна сна едет на подъём, учёба — сразу за ней."""
    sleep_start = NOW - timedelta(hours=6)
    events = [
        event("sleep", "СОН", sleep_start, NOW),
        event("z", "Зарядка", sleep_start + timedelta(hours=1),
              sleep_start + timedelta(hours=2)),
    ]
    handler, google = make_handler(events, [task("Учёба", "u-1", 45)],
                                   monkeypatch)
    moved, placed = handler.replan_day(dict(events[0]))

    assert moved == 1
    assert [m[0] for m in google.moved] == ["z"]
    assert google.moved[0][1] == NOW
    assert google.moved[0][2] - google.moved[0][1] == timedelta(hours=1)

    assert placed == 1
    assert google.created[0][1] == "u-1"
    assert google.created[0][2] == NOW + timedelta(hours=1)


def test_replan_day_only_fills_when_no_sleep_overlap(monkeypatch):
    """В окне сна пусто — только автозаполнение с момента подъёма."""
    sleep_start = NOW - timedelta(hours=6)
    events = [event("sleep", "СОН", sleep_start, NOW)]
    handler, google = make_handler(events, [task("Дело", "u-2", 30)],
                                   monkeypatch)
    moved, placed = handler.replan_day(dict(events[0]))

    assert moved == 0
    assert google.moved == []
    assert placed == 1
    assert google.created[0][1] == "u-2"
    assert google.created[0][2] == NOW


def test_replan_day_is_idempotent(monkeypatch):
    """Уже запланированный uuid не дублируется при заполнении дня."""
    sleep_start = NOW - timedelta(hours=6)
    events = [
        event("sleep", "СОН", sleep_start, NOW),
        event("pl", "Дело", NOW + timedelta(hours=1),
              NOW + timedelta(hours=2), description="u-2"),
    ]
    handler, google = make_handler(events, [task("Дело", "u-2", 30)],
                                   monkeypatch)
    moved, placed = handler.replan_day(dict(events[0]))
    assert moved == 0
    assert placed == 0
    assert google.created == []
