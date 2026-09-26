"""Юнит-тесты lib/taskflow/wake_slots.py — окна календаря и перенос из сна.

Проверяют compute_free_slots (дырки между событиями, минимум 15 мин,
курсор) и reschedule_sleep_events: события, начавшиеся в окне сна,
переносятся на окна после пробуждения в исходном порядке и с той же
длительностью. Сети нет: календарь — заглушка с move_event.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lib.taskflow.wake_slots import (compute_free_slots, event_datetime,
                                     reschedule_sleep_events)

TZ = timezone(timedelta(hours=3))
WAKE = datetime(2026, 9, 26, 8, 0, tzinfo=TZ)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def ev(eid, summary, start, end, description=""):
    return {"id": eid, "summary": summary, "start": iso(start),
            "end": iso(end), "description": description}


class FakeGoogle:
    """Заглушка календаря: помнит move_event, всегда успешный по умолчанию."""

    def __init__(self, move_ok=True):
        self.move_ok = move_ok
        self.moved: list[tuple] = []

    def move_event(self, event_id, new_start, new_end):
        self.moved.append((event_id, new_start, new_end))
        return self.move_ok


def test_event_datetime_skips_all_day():
    """Дата без времени («весь день») — None; ISO с зоной — aware datetime."""
    assert event_datetime("2026-09-26") is None
    assert event_datetime("") is None
    assert event_datetime(iso(WAKE)) == WAKE


def test_free_slots_between_and_after_events():
    """Дырка между событиями и хвост до 23:00 — оба окна ≥ 15 мин."""
    busy = [ev("a", "A", WAKE, WAKE + timedelta(minutes=30)),
            ev("b", "B", WAKE + timedelta(hours=1), WAKE + timedelta(hours=2))]
    free = compute_free_slots(busy, WAKE, WAKE.replace(hour=23))
    assert free[0]["start"] == WAKE + timedelta(minutes=30)
    assert free[0]["duration"] == 30
    assert free[-1]["start"] == WAKE + timedelta(hours=2)


def test_free_slots_drop_short_gap():
    """Дыпка короче 15 минут не считается свободным окном."""
    busy = [ev("a", "A", WAKE, WAKE + timedelta(minutes=10)),
            ev("b", "B", WAKE + timedelta(minutes=20),
               WAKE + timedelta(minutes=30))]
    free = compute_free_slots(busy, WAKE, WAKE.replace(hour=23))
    # короткий зазор 10..20 отброшен, первое окно — с конца b
    assert free[0]["start"] == WAKE + timedelta(minutes=30)


def test_reschedule_moves_sleep_window_events_in_order():
    """События окна сна едут на окна после подъёма по порядку, длительность та же."""
    sleep_start = WAKE - timedelta(hours=6)
    events = [
        ev("sleep", "СОН", sleep_start, WAKE),
        ev("t1", "Зарядка", sleep_start + timedelta(hours=1),
           sleep_start + timedelta(hours=2)),
        ev("t2", "Учёба", sleep_start + timedelta(hours=3),
           sleep_start + timedelta(hours=4)),
    ]
    g = FakeGoogle()
    moved, updated = reschedule_sleep_events(g, events, sleep_start, WAKE)
    assert moved == 2
    assert [m[0] for m in g.moved] == ["t1", "t2"]      # порядок сохранён
    assert g.moved[0][1] == WAKE                        # старт — с подъёма
    assert g.moved[0][2] - g.moved[0][1] == timedelta(hours=1)  # та же длит.
    t1 = next(e for e in updated if e["id"] == "t1")
    assert t1["start"] == WAKE.isoformat()              # обновлённый список


def test_reschedule_skips_sleep_and_after_wake():
    """Сам «СОН» и события после подъёма не двигаются."""
    sleep_start = WAKE - timedelta(hours=6)
    events = [
        ev("sleep", "СОН", sleep_start, WAKE),
        ev("later", "Вечер", WAKE + timedelta(hours=3),
           WAKE + timedelta(hours=4)),
    ]
    g = FakeGoogle()
    moved, _ = reschedule_sleep_events(g, events, sleep_start, WAKE)
    assert moved == 0
    assert g.moved == []


def test_reschedule_stop_when_move_fails():
    """Неудачный перенос — событие не считается перенесённым."""
    sleep_start = WAKE - timedelta(hours=6)
    events = [ev("t1", "Зарядка", sleep_start + timedelta(hours=1),
                 sleep_start + timedelta(hours=2))]
    moved, _ = reschedule_sleep_events(FakeGoogle(move_ok=False), events,
                                       sleep_start, WAKE)
    assert moved == 0
