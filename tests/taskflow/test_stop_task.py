"""Юнит-тесты ⏹-завершения запущенной задачи (lib/taskflow/stop_task.py).

Отличия ⏹ от ✅ (done.md §2 / stop.md §10): длительность по факту,
колонка B — накопительное время за день (сумма журнала + текущий
отрезок, а не усреднение плана), журнал и награда — только текущий
отрезок; O на выходе = 0.
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

    def __init__(self, row=None, event=None, was_new=True, journal=None):
        self.row = row if row is not None else task_row()
        self.event = event
        self.was_new = was_new
        self.journal = journal or []           # строки task_executions A..G
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
                          event=None):
        self.events_written.append((summary, task_uuid, minutes, end,
                                    event))
        return self.was_new

    def execution_rows(self):
        return list(self.journal)

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


def today_journal_entry(minutes: int, uuid: str = UUID) -> list:
    """Готовая строка журнала task_executions за сегодня (позиции A..G)."""
    return ["exec-id", str(NOW_MS - 3 * 3_600_000), str(minutes),
            "10", "Починить велосипед", uuid, "26.09.2026"]


def test_elapsed_and_cumulative_task_time():
    """Пустой журнал за сегодня: B = 0 + факт отрезка (без усреднения)."""
    api = FakeApi()
    result = stopped(api)
    assert result["ok"] is True and result["elapsed_minutes"] == 20
    assert column(api, "task_time") == 20           # 0 + 20, не ceil((30+20)/2)
    assert column(api, "start_date") == 0
    assert column(api, "task_finish_date") == 0    # стоп, не пауза


def test_task_time_is_cumulative_for_today():
    """Накопительное время: B = уже засчитанные сегодня + текущий отрезок."""
    api = FakeApi(journal=[["h1", "h2", "h3", "h4", "h5", "h6", "h7"],
                           today_journal_entry(15),
                           today_journal_entry(10)])
    stopped(api)
    assert column(api, "task_time") == 45          # 15 + 10 + 20


def test_journal_of_other_days_and_tasks_ignored():
    """Вчерашние отрезки и чужие задачи в сумму за сегодня не входят."""
    yesterday = today_journal_entry(60)
    yesterday[1] = str(NOW_MS - MS_PER_DAY)       # вчера
    api = FakeApi(journal=[today_journal_entry(15, uuid="другой-uuid"),
                           yesterday, today_journal_entry(4)])
    stopped(api)
    assert column(api, "task_time") == 24          # 4 + 20


def test_reward_and_journal_cover_only_current_segment():
    """Награда и строка журнала — по текущему отрезку, не по сумме дня."""
    api = FakeApi(journal=[today_journal_entry(15)])
    stopped(api)
    assert api.executions[0][2] == "20"
    assert api.hero_delta == pytest.approx(10.0)    # 20·1/2, не (35··)/2


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
    summary, uuid, minutes, end, event = api.events_written[0]
    assert (summary, uuid, minutes, end) == ("Починить велосипед", UUID, 20,
                                             NOW)


def test_existing_event_updated_and_title_kept():
    event = {"id": "ev-1", "summary": "Велосипед (план)", "colorId": ""}
    api = FakeApi(event=event, was_new=False)
    result = stopped(api)
    assert api.events_written[0][0] == "Велосипед (план)"
    assert api.events_written[0][4] == event
    assert result["event_was_new"] is False
    assert column(api, "break_multiplier") == "0"   # не сдвигается при update


def test_repeat_of_done_task_passes_the_marker_to_be_copied():
    """Второе выполнение за день: colorId=7 уходит в upsert как основа копии."""
    marker = {"id": "ev-1", "summary": "Велосипед", "colorId": "7"}
    api = FakeApi(event=marker, was_new=False)
    stopped(api)
    assert api.events_written[0][4] is marker


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


def test_paused_task_finalizes_from_accumulated_duration():
    """Пауза (start=0, накоплен task_finish_date): elapsed = накопленное."""
    api = FakeApi(row=task_row(start_date="0",
                               task_finish_date=str(25 * 60_000)))
    result = stopped(api)
    assert result["ok"] is True and result["elapsed_minutes"] == 25
    assert column(api, "task_finish_date") == 0   # закрыто, накопленное обнулено
    assert column(api, "task_time") == 25          # 0 накопленного журнала + 25


def test_missing_row_is_error():
    api = FakeApi()
    api.row = None
    assert stopped(api)["ok"] is False
