"""Фильтр переноса по uuid задачи (lib/taskflow/wake_slots.py).

«Я проснулся» двигает из окна сна только события, чьё описание содержит
task_uuid строки real_life_tasks. Ручные записи пользователя без такого
uuid («Игры на компе») обязаны оставаться на месте: их перенос был бы
самопроизвольной перестановкой чужого события. Сети нет: календарь —
заглушка с move_event.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lib.taskflow.wake_slots import reschedule_sleep_events

TZ = timezone(timedelta(hours=3))
WAKE = datetime(2026, 9, 26, 8, 0, tzinfo=TZ)

TU1 = "11111111-1111-1111-1111-111111111111"
TU2 = "22222222-2222-2222-2222-222222222222"


def iso(dt: datetime) -> str:
    return dt.isoformat()


def ev(eid, summary, start, end, description="", color=None):
    item = {"id": eid, "summary": summary, "start": iso(start),
            "end": iso(end), "description": description}
    if color is not None:
        item["colorId"] = color
    return item


class FakeGoogle:
    """Заглушка календаря: помнит move_event, всегда успешный по умолчанию."""

    def __init__(self, move_ok=True):
        self.move_ok = move_ok
        self.moved: list[tuple] = []

    def move_event(self, event_id, new_start, new_end):
        self.moved.append((event_id, new_start, new_end))
        return self.move_ok


def test_reschedule_skips_event_without_known_uuid():
    """Ручное событие без uuid задачи («Игры на компе») из сна НЕ уезжает."""
    sleep_start = WAKE - timedelta(hours=6)
    events = [
        ev("sleep", "СОН", sleep_start, WAKE),
        ev("games", "Игры на компе", sleep_start + timedelta(hours=1),
           sleep_start + timedelta(hours=2), color="2"),
    ]
    g = FakeGoogle()
    moved, _ = reschedule_sleep_events(
        g, events, sleep_start, WAKE, known_uuids={TU1})
    assert moved == 0
    assert g.moved == []


def test_reschedule_skips_unknown_uuid_event():
    """Описание с uuid, которого нет в таблице, — событие не двигаем."""
    sleep_start = WAKE - timedelta(hours=6)
    events = [
        ev("sleep", "СОН", sleep_start, WAKE),
        ev("stray", "Чужое", sleep_start + timedelta(hours=1),
           sleep_start + timedelta(hours=2), description=TU2),
    ]
    g = FakeGoogle()
    moved, _ = reschedule_sleep_events(
        g, events, sleep_start, WAKE, known_uuids={TU1})
    assert moved == 0
    assert g.moved == []


def test_reschedule_no_known_uuids_moves_nothing():
    """Пустой набор uuid (лист не прочитался) — из сна не уезжает ничего."""
    sleep_start = WAKE - timedelta(hours=6)
    events = [
        ev("sleep", "СОН", sleep_start, WAKE),
        ev("t1", "Зарядка", sleep_start + timedelta(hours=1),
           sleep_start + timedelta(hours=2), description=TU1),
    ]
    g = FakeGoogle()
    moved, _ = reschedule_sleep_events(
        g, events, sleep_start, WAKE, known_uuids=set())
    assert moved == 0
    assert g.moved == []
