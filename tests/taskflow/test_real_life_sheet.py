"""Юнит-тесты транспорта листов real_life_* (lib/taskflow/real_life_sheet.py).

Google-сервис подменяем заглушкой: проверяем диапазоны, RAW-режим,
UNFORMATTED_VALUE при чтении (иначе локаль ru ломает разбор чисел) и
что строка всегда выравнивается до 20 колонок A:T.
"""

from datetime import datetime, timedelta, timezone

import pytest

from lib.taskflow.cells import as_float, as_int
from lib.taskflow.real_life_sheet import COLS, RealLifeSheet

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 9, 26, 7, 30, tzinfo=TZ)
UUID = "f29ef6e3-f1f9-418c-a657-49ffa5dc9497"


class _Req:
    def __init__(self, result=None):
        self._result = result

    def execute(self):
        return self._result


class _Values:
    """Заглушка spreadsheets().values(): помнит вызовы, отдаёт заготовки."""

    def __init__(self, gets):
        self.gets = gets              # range → значения для get
        self.reads = []
        self.updates = []
        self.appended = []
        self.cleared = []

    def get(self, **kw):
        self.reads.append(kw)
        return _Req({"values": self.gets.get(kw["range"])})

    def update(self, **kw):
        self.updates.append(kw)
        return _Req({})

    def append(self, **kw):
        self.appended.append(kw)
        return _Req({})

    def clear(self, **kw):
        self.cleared.append(kw)
        return _Req({})


class _Sheets:
    def __init__(self, values):
        self._values = values

    def values(self):
        return self._values


class _Service:
    def __init__(self, values):
        self._sheets = _Sheets(values)

    def spreadsheets(self):
        return self._sheets


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


def make_api(gets=None, events=None, put_result="new-1"):
    values = _Values(gets or {})
    gcal = FakeGcal(events, put_result)
    api = RealLifeSheet(calendar=gcal, spreadsheet_id="SID")
    api._service = _Service(values)
    return api, values, gcal


def row(task_uuid=UUID, **changes):
    """Значения A:T строки задачи: часть колонок — текст, часть — числа."""
    values = ["Пробуждение ", "3", "описание", task_uuid, "1", "blue", "0",
              1790559350128, 10.5, "0000000", "6", "1", 1.5, "0", 0, 410,
              "", "", "", 1789654608006]
    for name, value in changes.items():
        values[COLS[name]] = value
    return values


def test_as_int_and_as_float_survive_junk_cells():
    """'' / None / NBSP / запятая-десятичная → число без исключения."""
    assert as_int("3") == 3 and as_int(3) == 3
    assert as_int("") == 0 and as_int(None) == 0 and as_int("abc", 5) == 5
    assert as_float("-0,1") == pytest.approx(-0.1)
    assert as_int("1\u00a0738\u00a0742") == 1738742
    assert as_float("1,185") == pytest.approx(1.185)


def test_find_task_row_reads_unformatted_and_pads_to_t():
    """Поиск по колонке D: чтение без форматирования и ровные 20 колонок."""
    api, values, _ = make_api({
        "real_life_tasks!A1:T": [["task_title"], row()[:4] + ["хвост"]]})
    found = api.find_task_row(UUID)
    assert found is not None
    idx, cells = found
    assert idx == 2 and len(cells) == 20
    assert values.reads[0]["valueRenderOption"] == "UNFORMATTED_VALUE"
    assert values.reads[0]["spreadsheetId"] == "SID"

    api, _, _ = make_api({"real_life_tasks!A1:T": [["task_title"], ["другое"]]})
    assert api.find_task_row(UUID) is None


def test_write_task_row_updates_whole_row_raw():
    """Один update A{row}:T{row} в RAW — типы ячеек сохраняются как прочитаны."""
    api, values, _ = make_api()
    api.write_task_row(7, row()[:10])
    sent = values.updates[0]
    assert sent["range"] == "real_life_tasks!A7:T7"
    assert sent["valueInputOption"] == "RAW"
    body = sent["body"]["values"][0]
    assert len(body) == 20 and body[1] == "3" and body[7] == 1790559350128


def test_find_done_event_scans_only_today():
    """Событие ищется по uuid в описании и только в границах сегодня."""
    event = {"id": "ev-1", "summary": "Пробуждение", "description": UUID}
    api, _, gcal = make_api(events=[{"id": "e2", "description": "нет"}, event])
    assert api.find_done_event(UUID, NOW) == event
    time_min, time_max = gcal.ranges[0]
    assert time_min == NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    assert time_max == time_min + timedelta(days=1)
    assert api.find_done_event("другой-uuid", NOW) is None


def test_upsert_done_event_reports_new_only_and_raises_on_failure():
    """True — когда вставили новое; False — когда обновили; сбой — RuntimeError."""
    api, _, gcal = make_api()
    assert api.upsert_done_event("Пробуждение", UUID, 3, NOW) is True
    assert gcal.put[0]["event_id"] is None
    assert api.upsert_done_event("Пробуждение", UUID, 3, NOW,
                                 event_id="ev-1") is False
    assert gcal.put[1]["event_id"] == "ev-1"

    broken, _, _ = make_api(put_result="")
    with pytest.raises(RuntimeError):
        broken.upsert_done_event("Пробуждение", UUID, 3, NOW)


def test_append_execution_uses_journal_range():
    """Журнал: append в task_executions!A:G одним рядом, RAW."""
    api, values, _ = make_api()
    api.append_execution(["id", "1758860000000", "3", "1.5", "Пробуждение ",
                          UUID, "26.09.2026"])
    sent = values.appended[0]
    assert sent["range"] == "task_executions!A:G"
    assert sent["valueInputOption"] == "RAW"
    assert len(sent["body"]["values"]) == 1


def test_hero_money_updates_existing_row_or_creates_it():
    """hero_money: точечный update B по строке кода; нет строки — append."""
    api, values, _ = make_api({
        "real_life_hero!A1:B": [["code", "value"], ["hero_name", "biyk"],
                                ["hero_level", "11"],
                                ["hero_money", "15134.145"]]})
    api.add_hero_money(1.5)
    sent = values.updates[0]
    assert sent["range"] == "real_life_hero!B4"
    assert sent["body"]["values"] == [[15135.645]]

    api, values, _ = make_api({"real_life_hero!A1:B": [["code", "value"]]})
    api.add_hero_money(2.0)
    assert values.appended[0]["body"]["values"] == [["hero_money", 2.0]]
