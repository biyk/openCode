"""Юнит-тесты засчёта задачи выполненной (lib/taskflow/done_task.py).

FakeApi вместо Google: три отличия ✅ от ⏹ (done.md §2) — план в колонке B
не меняется, журнал и награда по плану, — плюс порядок операций и защита
от повторного засчёта в тот же день.
"""

from datetime import datetime, timedelta, timezone

import pytest

from lib.taskflow.done_calc import MS_PER_DAY
from lib.taskflow.done_task import mark_task_done
from lib.taskflow.real_life_sheet import COLS

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 9, 26, 7, 30, tzinfo=TZ)
NOW_MS = int(NOW.timestamp() * 1000)
LAST_MS = NOW_MS - 2 * MS_PER_DAY          # позавчера: 2 дня просрочки
UUID = "f29ef6e3-f1f9-418c-a657-49ffa5dc9497"


def task_row(**changes) -> list:
    """Строка real_life_tasks как в живой таблице: часть значений — текст."""
    row = ["Пробуждение ", "3", "Проверить реальность на сон", UUID, "1",
           "blue", "0", "1790559350128", "10,5", "0000000", "6", "1",
           "1,5", "0", "0", "410", "", "", "", str(LAST_MS)]
    for name, value in changes.items():
        row[COLS[name]] = value
    return row


class FakeApi:
    """Заглушка RealLifeSheet: помнит записи, отдаёт подготовленную строку."""

    def __init__(self, row=None, event=None, was_new=True) -> None:
        self.row = row if row is not None else task_row()
        self.event = event                       # сегодняшнее событие с uuid
        self.was_new = was_new                   # ответ upsert_done_event
        self.rows_written: list[tuple[int, list]] = []
        self.executions: list[list] = []
        self.hero_delta = 0.0
        self.events_written: list[tuple] = []

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


def done(api: FakeApi) -> dict:
    return mark_task_done(UUID, api=api, now=NOW)


def column(api: FakeApi, name: str):
    """Значение колонки записанной строки A:T."""
    return api.rows_written[0][1][COLS[name]]


def test_plan_column_b_and_start_column_g_untouched():
    """Главное отличие ✅: колонка B (план) не меняется, G остаётся 0."""
    api = FakeApi()
    result = done(api)
    assert result["ok"] is True and result["time_spent"] == 3
    assert column(api, "task_time") == "3"        # как в исходной строке
    assert column(api, "start_date") == "0"
    assert api.rows_written[0][0] == 7            # строка не сдвинулась


def test_counters_written_from_plan_and_now():
    """H/I/M/O/P/T после ✅: награда и журнал по плану, отметка — сейчас."""
    api = FakeApi()
    result = done(api)
    assert column(api, "number_of_executions") == 411
    assert column(api, "last_execution") == NOW_MS
    assert column(api, "task_finish_date") == 0
    assert column(api, "money_reward") == pytest.approx(1.5)   # 3 · 1 / 2 · 1
    expected_ri = (10.5 + 2.0) * 0.9 / 2 - 0.1     # новый ивент → −0.1
    assert column(api, "repeat_index") == pytest.approx(expected_ri)
    assert column(api, "task_date") == NOW_MS + int(
        round(expected_ri * MS_PER_DAY))
    assert result["money"] == pytest.approx(1.5)


def test_execution_row_uses_planned_minutes_not_elapsed():
    """Журнал: execution_time = план (3), а не фактическая длительность."""
    api = FakeApi()
    done(api)
    assert len(api.executions) == 1
    cells = api.executions[0]
    assert cells[1] == str(NOW_MS)                # execution_date
    assert cells[2] == "3"                        # execution_time = план
    assert cells[3] == "1.5"                      # gained_gold
    assert cells[4] == "Пробуждение "             # task_title как в таблице
    assert cells[5] == UUID and cells[6] == "26.09.2026"
    assert api.hero_delta == pytest.approx(1.5)   # награда герою


def test_once_mode_skips_journal_and_hero_but_writes_row():
    """repeat_mode=5 (однократная): строка и галочка есть, журнал и награда — нет."""
    api = FakeApi(row=task_row(repeat_mode="5"))
    done(api)
    assert api.rows_written and api.events_written
    assert api.executions == [] and api.hero_delta == 0.0


def test_done_event_created_with_planned_duration():
    """Галочка colorId=7: длительность = план, конец = момент команды."""
    api = FakeApi()
    done(api)
    summary, uuid, minutes, end, event_id = api.events_written[0]
    assert (summary, uuid, minutes, end, event_id) == ("Пробуждение", UUID, 3,
                                                       NOW, None)


def test_existing_event_is_updated_and_its_title_kept():
    """Плановое событие сегодня → update вместо insert, заголовок его собственный."""
    event = {"id": "ev-1", "summary": "Пробуждение (план)"}
    api = FakeApi(event=event, was_new=False)
    result = done(api)
    assert api.events_written[0][0] == "Пробуждение (план)"
    assert api.events_written[0][4] == "ev-1"
    assert result["event_was_new"] is False


def test_repeat_bonus_only_when_event_is_new():
    """break_multiplier и task_sort сдвигаются при новом ивенте и нет — при update."""
    new_event = FakeApi()
    done(new_event)
    assert column(new_event, "break_multiplier") == pytest.approx(1.0)
    assert column(new_event, "task_sort") == pytest.approx(0.98)
    kept = FakeApi(event={"id": "ev-1", "summary": "Пробуждение"},
                   was_new=False)
    done(kept)
    assert column(kept, "break_multiplier") == "0"      # как в исходной строке
    assert column(kept, "task_sort") == "1"


def test_second_wake_same_day_is_skipped_without_writes():
    """Повторная команда в тот же день: не сдвигает ни строку, ни журнал."""
    api = FakeApi(row=task_row(last_execution=str(NOW_MS)))
    result = done(api)
    assert result["skipped"] is True and result["ok"] is True
    assert api.rows_written == [] and api.executions == []
    assert api.events_written == []

    forced = FakeApi(row=task_row(last_execution=str(NOW_MS)))
    assert mark_task_done(UUID, api=forced, now=NOW,
                          once_per_day=False)["ok"] is True
    assert forced.rows_written and forced.executions


def test_running_task_requires_stop_and_missing_row_is_error():
    """start_date != 0 → RuntimeError (нужен ⏹); нет строки → ok=False."""
    running = FakeApi(row=task_row(start_date=str(NOW_MS - 1000)))
    with pytest.raises(RuntimeError):
        done(running)
    assert running.rows_written == []
    missing = FakeApi()
    missing.row = None
    result = mark_task_done(UUID, api=missing, now=NOW)
    assert result["ok"] is False and "не найдена" in result["error"]
