"""Тесты команды «я начал/я приступил {задача}» (lib.task_start)."""

from datetime import datetime, timedelta, timezone

from lib.task_start import TaskStartHandler
from lib.task_start_sheet import parse_ms_cell

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=TZ)
NOW_MS = int(NOW.timestamp() * 1000)
UUID = "6a1c2d3e-4f50-5152-a3a4-b5c6d7e8f901"


class FakeCalendar:
    """Календарь-заглушка: отдаёт заранее заданные события."""

    def __init__(self, events):
        self.events = events
        self.calls = []

    def list_events_between(self, start, end):
        self.calls.append((start, end))
        return self.events


class FakeSheet:
    """Таблица-заглушка: запись только в G, значения клеток на чтении."""

    def __init__(self, row=None, start=0, finish=0):
        self.row = row
        self.start = start
        self.finish = finish
        self.written = None   # (row_idx, start_ms)

    def find_row_by_uuid(self, task_uuid):
        return self.row if task_uuid == UUID else None

    def read_start_finish(self, row_idx):
        return self.start, self.finish

    def write_start(self, row_idx, start_ms):
        self.written = (row_idx, start_ms)


def event(title, description=f"ссылка https://x/#/t uuid {UUID}"):
    return {"id": "e1", "summary": title, "description": description,
            "start": NOW.isoformat(), "end": NOW.isoformat()}


def handler(events, row=5, start=0, finish=0):
    cal = FakeCalendar(events)
    sheet = FakeSheet(row=row, start=start, finish=finish)
    return TaskStartHandler(gcal=cal, sheet=sheet, now=NOW), cal, sheet


def test_start_writes_only_g_with_now_ms():
    h, _, sheet = handler([event("Починить велосипед")])
    result = h.start_task("починить велосипед")
    assert result["ok"] is True
    assert sheet.written == (5, NOW_MS)   # finish=0 → чистое now


def test_start_resumes_with_saved_pause_duration():
    h, _, sheet = handler([event("Отчёт")], finish=123456)
    result = h.start_task("отчет")           # ё/е и регистр не важны
    assert result["ok"] is True
    assert sheet.written == (5, NOW_MS - 123456)


def test_start_rejects_already_running_task():
    h, _, sheet = handler([event("Отчёт")], start=NOW_MS - 1)
    result = h.start_task("отчет")
    assert result["ok"] is False and "уже запущена" in result["error"]
    assert sheet.written is None


def test_noise_words_stripped_before_search():
    h, _, sheet = handler([event("Помыть пол")])
    result = h.start_task("задачу помыть пол")
    assert result["ok"] is True
    assert sheet.written is not None


def test_preposition_kei_stripped():
    h, _, _ = handler([event("Отчет")])
    assert h.find_task_event("к отчету") is not None


def test_unknown_task_and_missing_uuid_and_row_are_errors():
    h, _, sheet = handler([event("Отчёт")])
    assert h.start_task("сжечь мост")["ok"] is False
    assert sheet.written is None
    no_uuid = handler([event("Отчёт", description="без идентификатора")])[0]
    assert "нет uuid" in no_uuid.start_task("отчет")["error"]
    absent = handler([event("Отчёт")], row=None)[0]
    assert "не найдена в таблице" in absent.start_task("отчет")["error"]


def test_parse_ms_cell_variants():
    assert parse_ms_cell("") == 0
    assert parse_ms_cell(None) == 0
    assert parse_ms_cell("0") == 0
    assert parse_ms_cell("1738742400000") == 1738742400000
    assert parse_ms_cell("1\u00a0738\u00a0742") == 1738742  # NBSP вырезаются
    assert parse_ms_cell("1738742400000.0") == 1738742400000
