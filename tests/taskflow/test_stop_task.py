"""Юнит-тесты ⏹-завершения запущенной задачи (lib/taskflow/stop_task.py).

Отличия ⏹ от ✅ (done.md §2 / stop.md §10): длительность по факту, колонка
B усредняется, журнал и награда по факту; O на выходе = 0.
"""

from datetime import datetime, timedelta, timezone

import pytest

from lib.taskflow.done_calc import MS_PER_DAY
from lib.taskflow.real_life_sheet import COLS
from lib.taskflow.stop_task import stop_task

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 9, 26, 8, 0, tzinfo=TZ)
NOW_MS = int(NOW.timestamp() * 1000)
START_MS = NOW_MS - 20 * 60_000            # в работе 20 минут
LAST_MS = NOW_MS - 2 * MS_PER_DAY          # позавчера: 2 дня просрочки
UUID = "6a1c2d3e-4f50-5152-a3a4-b5c6d7e8f901"


def task_row(**changes) -> list:
    """Строка real_life_tasks: часть значений — текст (как в живой таблице)."""
    row = ["Починить велосипед", "30", "Описание", UUID, "1", "blue",
           str(START_MS), "1790559350128", "10,5", "0000000", "6", "1",
           "1,5", "0", "0", "410", "", "", "", str(LAST_MS)]
    for name, value in changes.items():
        row[COLS[name]] = value
    return row


class FakeApi:
    """Заглушка RealLifeSheet: помнит записи, отдаёт подготовленную строку."""

    def __init__(self, row=None, event=None, was_new=True) -> None:
        self.row = row if row is not None else task_row()
        self.event = event
        self.was_new = was_new
        self.rows_written = []
        self.executions = []
        self.hero_delta = 0.0
        self.events_written = []

    def find_task_row(self, task_uuid):
        if self.row is None or task_uuid != UUID:
            return None
        return 7, list(self.row)

    def find_done_event(self, task_uuid, now):
        return self.event

    def upsert_done_event(self, summary, task_uuid, minutes, end,
                          event_id=None):
        self.events_written.append((summary, task_uuid, minutes, end,
                                    event_id))
        return self.was_new

    def execution_rows(self):
        return []

    def write_task_row(self, row_idx, values):
        self.rows_written.append((row_idx, values))

    def append_execution(self, cells):
        self.executions.append(cells)

    def add_hero_money(self, delta):
        self.hero_delta += delta


def stopped(api):
    return stop_task(UUID, api=api, now=NOW)


def column(api, name):
    """Значение колонки записанной строки A:T."""
    return api.rows_written[0][1][COLS[name]]


def test_elapsed_and_averaged_task_time():
    api = FakeApi()
    result = stopped(api)
    assert result["ok"] is True and result["elapsed_minutes"] == 20
    assert column(api, "task_time") == 25          # ceil((30 + 20) / 2)
    assert column(api, "start_date") == 0
    assert column(api, "task_finish_date") == 0    # стоп, не пауза


def test_counters_and_reward_by_elapsed():
    api = FakeApi()
    result = stopped(api)
    assert column(api, "number_of_executions") == 411
    assert column(api, "last_execution") == NOW_MS
    assert column(api, "money_reward") == pytest.approx(10.0)  # 20·1/2·1
    expected_ri = (10.5 + 2.0) * 0.9 / 2 - 0.1
    assert column(api, "repeat_index") == pytest.approx(expected_ri)
    assert result["money"] == pytest.approx(10.0)


def test_execution_row_uses_elapsed_minutes():
    api = FakeApi()
    stopped(api)
    assert len(api.executions) == 1
    assert api.executions[0][2] == "20"             # execution_time = факт
    assert api.executions[0][6] == "26.09.2026"
    assert api.hero_delta == pytest.approx(10.0)


def test_done_event_created_with_elapsed_duration():
    api = FakeApi()
    stopped(api)
    summary, uuid, minutes, end, event_id = api.events_written[0]
    assert (summary, uuid, minutes, end) == ("Починить велосипед", UUID, 20,
                                             NOW)


def test_existing_event_updated_and_title_kept():
    event = {"id": "ev-1", "summary": "Велосипед (план)"}
    api = FakeApi(event=event, was_new=False)
    result = stopped(api)
    assert api.events_written[0][0] == "Велосипед (план)"
    assert api.events_written[0][4] == "ev-1"
    assert result["event_was_new"] is False
    assert column(api, "break_multiplier") == "0"   # не сдвигается при update


def test_once_mode_skips_journal_and_hero_but_writes_row():
    api = FakeApi(row=task_row(repeat_mode="5"))
    stopped(api)
    assert api.rows_written and api.events_written
    assert api.executions == [] and api.hero_delta == 0.0


def test_not_running_task_raises():
    api = FakeApi(row=task_row(start_date="0"))
    with pytest.raises(RuntimeError):
        stopped(api)
    assert api.rows_written == []


def test_missing_row_is_error():
    api = FakeApi()
    api.row = None
    assert stopped(api)["ok"] is False
