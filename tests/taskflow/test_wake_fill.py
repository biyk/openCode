"""Юнит-тесты lib/taskflow/wake_fill.py — автозаполнение остатка дня.

Проверяют приоритет taskSort, фильтр подлежащих задач, идемпотентность по
task_uuid, конфликт excludes и «съедание» окна. В Таблицы не пишется
(FakeSheet только отдаёт задачи), сети нет (FakeGoogle считает insert).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lib.taskflow.wake_fill import fill_calendar, task_sort_key

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 9, 26, 8, 0, tzinfo=TZ)
NOW_MS = int(NOW.timestamp() * 1000)


def task(title, uuid, minutes, sort=0, break_mult=0,
         task_date=None, excludes=""):
    return {
        "task_title": title, "task_uuid": uuid, "task_time": minutes,
        "task_sort": sort, "break_multiplier": break_mult,
        "task_date": task_date if task_date is not None else NOW_MS - 1000,
        "excludes": excludes,
    }


def scheduled(eid, summary, uuid, start, minutes):
    return {"id": eid, "summary": summary, "description": uuid,
            "start": start.isoformat(),
            "end": (start + timedelta(minutes=minutes)).isoformat()}


class FakeSheet:
    """Заглушка RealLifeSheet: только чтение списка задач."""

    def __init__(self, tasks):
        self._tasks = tasks

    def read_all_tasks(self):
        return list(self._tasks)


class FakeGoogle:
    """Заглушка календаря: считает create_task_event, ничего не фильтрует."""

    def __init__(self):
        self.created: list[tuple] = []

    def create_task_event(self, summary, description, start, end):
        self.created.append((summary, description, start, end))
        return "id-" + description


def test_fill_places_by_priority_and_consumes_slot():
    """Важная (меньший ключ) встаёт первой, следующая — сразу за ней."""
    tasks = [task("Длинная", "u-long", 60, sort=10),
             task("Важная", "u-a", 30, sort=1)]
    g = FakeGoogle()
    placed = fill_calendar(g, FakeSheet(tasks), [], NOW)
    assert placed == 2
    assert g.created[0][1] == "u-a"                 # важная первой
    assert g.created[0][2] == NOW                   # с начала рабочего окна
    assert g.created[1][2] == NOW + timedelta(minutes=30)


def test_fill_skips_already_scheduled():
    """Задача с uuid в описании события дня не дублируется (идемпотентность)."""
    tasks = [task("Есть", "u-x", 30)]
    events = [scheduled("e", "Есть", "u-x", NOW, 30)]
    g = FakeGoogle()
    assert fill_calendar(g, FakeSheet(tasks), events, NOW) == 0
    assert g.created == []


def test_fill_respects_excludes():
    """Конфликт excludes (uuid уже в календаре) — задача не планируется."""
    tasks = [task("Нельзя", "u-b", 30, excludes="u-a")]
    events = [scheduled("e", "A", "u-a", NOW, 30)]
    g = FakeGoogle()
    assert fill_calendar(g, FakeSheet(tasks), events, NOW) == 0


def test_fill_ignores_header_and_untimed():
    """Тех. строка task_title и нулевая длительность не планируются."""
    tasks = [task("task_title", "hdr", 30), task("Без времени", "u0", 0)]
    g = FakeGoogle()
    assert fill_calendar(g, FakeSheet(tasks), [], NOW) == 0


def test_task_sort_raises_overdue():
    """Просроченная с большим break_multiplier имеет меньший ключ → раньше."""
    old = NOW_MS - int(timedelta(days=3).total_seconds() * 1000)
    fresh = NOW_MS - 1000
    assert task_sort_key(task("x", "a", 30, sort=5, break_mult=10,
                              task_date=old), NOW) < \
        task_sort_key(task("y", "b", 30, sort=5, break_mult=10,
                           task_date=fresh), NOW)
