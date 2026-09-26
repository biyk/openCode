"""Юнит-тесты голосовой команды «завершил задачу …» (lib.task_complete).

Ветвь ⏹/✅ выбирается по start_date строки; поиск по названию идёт через
переиспользуемый TaskStartHandler (сегодняшние события календаря).
"""

from datetime import datetime, timedelta, timezone

from lib.task_complete import TaskCompleteHandler

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=TZ)
NOW_MS = int(NOW.timestamp() * 1000)
UUID = "6a1c2d3e-4f50-5152-a3a4-b5c6d7e8f901"


def row_for(start_date):
    """Минимальная строка A:T: index 3 = uuid, index 6 = start_date."""
    row = [""] * 20
    row[0] = "Задача"
    row[3] = UUID
    row[6] = str(start_date)
    return row


class FakeCalendar:
    def __init__(self, events):
        self.events = events

    def list_events_between(self, start, end):
        return self.events


class FakeApi:
    """Заглушка RealLifeSheet для разбора названия (engine замокан отдельно)."""

    def __init__(self, start_date, running=None):
        self.start_date = start_date
        self.running = running

    def find_running_task(self):
        return self.running

    def find_task_row(self, task_uuid):
        return 3, row_for(self.start_date)


def event(title, description=f"https://x/#/t uuid {UUID}"):
    return {"id": "e1", "summary": title, "description": description}


def handler(events, start_date, running=None):
    cal = FakeCalendar(events)
    api = FakeApi(start_date, running=running)
    return TaskCompleteHandler(gcal=cal, api=api, now=NOW)


def ok_stop(uuid, api=None, now=None):
    return {"ok": True, "elapsed_minutes": 5, "money": 1.0}


def ok_done(uuid, api=None, now=None):
    return {"ok": True, "time_spent": 3, "money": 1.5}


def test_named_running_task_goes_stop(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        "lib.task_complete.stop_task",
        lambda u, api=None, now=None: calls.update(stop=u) or ok_stop(u))
    monkeypatch.setattr("lib.task_complete.mark_task_done", ok_done)
    h = handler([event("Починить велосипед")], start_date=NOW_MS - 1000)
    result = h.complete_task("починить велосипед")
    assert result["branch"] == "⏹" and result["ok"] is True
    assert calls["stop"] == UUID


def test_named_not_running_task_goes_done(monkeypatch):
    calls = {}
    monkeypatch.setattr("lib.task_complete.stop_task", ok_stop)
    monkeypatch.setattr(
        "lib.task_complete.mark_task_done",
        lambda u, api=None, now=None: calls.update(done=u) or ok_done(u))
    h = handler([event("Отчёт")], start_date=0)
    result = h.complete_task("отчет")
    assert result["branch"] == "✅" and result["ok"] is True
    assert calls["done"] == UUID


def test_empty_name_completes_running_task(monkeypatch):
    monkeypatch.setattr("lib.task_complete.stop_task", ok_stop)
    running = {"row": 3, "uuid": UUID, "title": "Задача"}
    h = handler([], start_date=NOW_MS - 1000, running=running)
    result = h.complete_task("")
    assert result["branch"] == "⏹" and result["ok"] is True


def test_empty_name_without_running_task_is_error():
    h = handler([], start_date=0, running=None)
    result = h.complete_task("")
    assert result["ok"] is False and "нет запущенной" in result["error"]


def test_unknown_name_is_error():
    h = handler([event("Отчёт")], start_date=0)
    result = h.complete_task("сжечь мост")
    assert result["ok"] is False and "не найдена" in result["error"]


def test_event_without_uuid_is_error():
    h = handler([event("Отчёт", description="без идентификатора")],
                start_date=0)
    result = h.complete_task("отчет")
    assert result["ok"] is False and "нет uuid" in result["error"]
