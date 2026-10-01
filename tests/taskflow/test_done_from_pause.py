"""Юнит-тесты завершения задачи из паузы (накопительное время за день).

Новый алгоритм JS-клиента (deb5b567): ⏸ пишет отрезки в журнал с наградой
и ставит сентинел task_finish_date=1; финальное ✅ по такой строке ставит
в колонку B суммарное время за день по журналу task_executions и НЕ
начисляет награду/строку журнала повторно (аналог skipReward).
"""

import pytest

from lib.taskflow.done_task import mark_task_done
from lib.taskflow.real_life_sheet import COLS
from tests.taskflow.test_done_task import UUID, NOW, NOW_MS, FakeApi, task_row


def journal_entry(minutes: int, ago_ms: int = 3_600_000,
                  uuid: str = UUID) -> list:
    """Строка журнала task_executions (позиции A..G) — час назад по умолчанию."""
    return ["exec-id", str(NOW_MS - ago_ms), str(minutes), "4",
            "Пробуждение", uuid, "26.09.2026"]


class JournalApi(FakeApi):
    """FakeApi + живой журнал для sum_executed_minutes_today."""

    def __init__(self, journal=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.journal = journal or []

    def execution_rows(self):
        return list(self.journal)


def paused_api(**kwargs) -> JournalApi:
    row = task_row(task_finish_date=str(kwargs.pop("finish", "1")))
    return JournalApi(row=row, **kwargs)


def done(api) -> dict:
    return mark_task_done(UUID, api=api, now=NOW)


def column(api, name):
    return api.rows_written[0][1][COLS[name]]


def test_done_from_pause_writes_cumulative_time_no_reward():
    """Из паузы (G=0, O=1): B = сумма журнала за день, награда/журнал — нет."""
    api = paused_api(journal=[["h"] * 7, journal_entry(15), journal_entry(10)])
    result = done(api)
    assert result["ok"] is True and result["time_spent"] == 25
    assert result["skip_reward"] is True
    assert column(api, "task_time") == 25          # накопительное за день
    assert api.executions == [] and api.hero_delta == 0.0
    assert api.events_written[0][2] == 25          # галочка — на сумму дня


def test_done_from_pause_empty_journal_keeps_plan_and_reward():
    """Пауза без отрезков в журнале (сентинел O=1): считаем как обычное ✅."""
    api = paused_api()
    result = done(api)
    assert result["time_spent"] == 3 and result["skip_reward"] is False
    assert column(api, "task_time") == "3"         # план не тронут
    assert api.executions and api.hero_delta == pytest.approx(1.5)


def test_done_from_pause_ignores_other_days_and_tasks():
    """В сумму дня для паузы входят только сегодняшние свои отрезки."""
    api = paused_api(journal=[journal_entry(60, ago_ms=40 * 3_600_000),
                              journal_entry(9, uuid="чужой"),
                              journal_entry(7)])
    result = done(api)
    assert result["time_spent"] == 7
    assert column(api, "task_time") == 7


def test_row_still_finalized_when_reward_skipped():
    """skipReward глушит только герой и журнал: строка/H/I/O/P пишутся."""
    api = paused_api(journal=[journal_entry(15)])
    result = done(api)
    assert api.rows_written and result["ok"] is True
    assert column(api, "number_of_executions") == 411
    assert column(api, "last_execution") == NOW_MS
    assert column(api, "task_finish_date") == 0    # пауза закрыта
