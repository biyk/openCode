"""Юнит-тесты события-галочки: find/upsert в RealLifeSheet (done.md §7).

Главное правило: одно мероприятие можно выполнить в день несколько раз,
и каждое выполнение обязано остаться в том промежутке, в котором оно
было сделано. Поэтому плановое событие (без цвета) — переносим, а уже
галочку colorId=7 — не двигаем, вставляем полноценную копию рядом.
"""

from datetime import datetime, timedelta, timezone

import pytest

from lib.taskflow.real_life_sheet import RealLifeSheet

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 9, 26, 7, 30, tzinfo=TZ)
UUID = "f29ef6e3-f1f9-418c-a657-49ffa5dc9497"


class FakeGcal:
    """Календарь-заглушка: сегодняшние события и запись галочки."""

    def __init__(self, events=None, put_result="new-1"):
        self.events = events or []
        self.put_result = put_result
        self.ranges = []
        self.put = []

    def list_events_between(self, time_min, time_max, limit=50):
        self.ranges.append((time_min, time_max))
        return self.events

    def put_done_event(self, **kw):
        self.put.append(kw)
        return self.put_result


def make_api(events=None, put_result="new-1"):
    gcal = FakeGcal(events, put_result)
    return RealLifeSheet(calendar=gcal, spreadsheet_id="SID"), gcal


def test_find_done_event_scans_only_today():
    """Событие ищется по uuid в описании и только в границах сегодня."""
    event = {"id": "ev-1", "summary": "Пробуждение", "description": UUID}
    api, gcal = make_api([{"id": "e2", "description": "нет"}, event])
    assert api.find_done_event(UUID, NOW) == event
    time_min, time_max = gcal.ranges[0]
    assert time_min == NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    assert time_max == time_min + timedelta(days=1)
    assert api.find_done_event("другой-uuid", NOW) is None


def test_find_done_event_returns_first_of_the_day():
    """Найденное — самое раннее сегодняшнее событие задачи (порядок дня)."""
    first = {"id": "ev-1", "description": UUID, "colorId": "7"}
    api, _ = make_api([first, {"id": "ev-2", "description": UUID}])
    assert api.find_done_event(UUID, NOW) == first


def test_upsert_moves_planned_event_of_today():
    """Первое выполнение: плановое событие (без цвета) переезжает на свой интервал."""
    api, gcal = make_api()
    planned = {"id": "ev-1", "summary": "Пробуждение", "colorId": ""}
    assert api.upsert_done_event("Пробуждение", UUID, 3, NOW,
                                 event=planned) is False
    assert gcal.put[0]["event_id"] == "ev-1"


def test_upsert_copies_event_already_done_today():
    """Повтор в тот же день: галочку colorId=7 не двигаем — вставляется копия.

    Иначе второе выполнение стирало бы первый промежуток, хотя мероприятие
    можно делать несколько раз в день.
    """
    api, gcal = make_api()
    marker = {"id": "ev-1", "summary": "Пробуждение", "colorId": "7"}
    assert api.upsert_done_event("Пробуждение", UUID, 3, NOW,
                                 event=marker) is False
    assert gcal.put[0]["event_id"] is None          # insert, а не update


def test_upsert_without_event_creates_marker_and_reports_new():
    """Сегодня события не было вовсе: вставляем галочку и поднимаем was_new."""
    api, gcal = make_api()
    assert api.upsert_done_event("Пробуждение", UUID, 3, NOW) is True
    assert gcal.put[0]["event_id"] is None
    api, gcal = make_api()
    assert api.upsert_done_event("Пробуждение", UUID, 3, NOW,
                                 event={"summary": "без id"}) is False
    assert gcal.put[0]["event_id"] is None


def test_upsert_raises_on_calendar_failure():
    """Сбой запроса — RuntimeError: вызывающий не должен двигать счётчики."""
    api, _ = make_api(put_result="")
    with pytest.raises(RuntimeError):
        api.upsert_done_event("Пробуждение", UUID, 3, NOW)
