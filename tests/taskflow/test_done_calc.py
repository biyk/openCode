"""Юнит-тесты формул засчёта выполнения (lib/taskflow/done_calc.py).

Всё считается на фиксированном времени без Google: повтор, дата след-
ующего выполнения по repeat_mode, награда по плану, дисциплина за 30 дней.
"""

from datetime import datetime, timedelta, timezone

import pytest

from lib.taskflow.done_calc import (
    MS_PER_DAY,
    average_discipline,
    is_same_local_day,
    money_reward,
    next_task_date,
    repeat_real,
)

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 9, 26, 7, 30, tzinfo=TZ)      # суббота
NOW_MS = int(NOW.timestamp() * 1000)
HEADER = ["execution_date", "execution_time"]


def ms(day: datetime) -> int:
    return int(day.timestamp() * 1000)


def history(minutes_by_ago: dict[int, int]) -> list[list[str]]:
    """Строки журнала: {дней назад: минуты} — остальное время пустое."""
    rows = [HEADER]
    for ago, spent in minutes_by_ago.items():
        rows.append([str(ms(NOW - timedelta(days=ago))), str(spent)])
    return rows


def test_repeat_real_averages_index_and_lateness():
    """(индекс + дни просрочки) · 0.9 / 2; новый ивент снимает 0.1."""
    assert repeat_real(10.0, 4.0, False) == (10.0 + 4.0) * 0.9 / 2
    assert repeat_real(10.0, 4.0, True) == (10.0 + 4.0) * 0.9 / 2 - 0.1


def test_next_task_date_daily_monthly_yearly():
    """Режимы 0/1/2: 00:00:01 следующего месяца/года/дня."""
    assert next_task_date("0", 0, "", NOW) == ms(
        datetime(2026, 9, 27, 0, 0, 1, tzinfo=TZ))
    assert next_task_date("1", 0, "", NOW) == ms(
        datetime(2026, 10, 26, 0, 0, 1, tzinfo=TZ))
    assert next_task_date("2", 0, "", NOW) == ms(
        datetime(2027, 9, 26, 0, 0, 1, tzinfo=TZ))


def test_next_task_date_month_clamps_short_month():
    """31.01 → 28.02: число ограничиваем длиной следующего месяца."""
    winter = datetime(2026, 1, 31, 12, 0, tzinfo=TZ)
    assert next_task_date("1", 0, "", winter) == ms(
        datetime(2026, 2, 28, 0, 0, 1, tzinfo=TZ))
    leap = datetime(2024, 2, 29, 12, 0, tzinfo=TZ)
    assert next_task_date("2", 0, "", leap) == ms(
        datetime(2025, 2, 28, 0, 0, 1, tzinfo=TZ))


def test_next_task_date_interval_modes():
    """Режимы 5/6: now + repeat_index дней (дробные дни округляем)."""
    assert next_task_date("6", 2.5, "", NOW) == NOW_MS + int(
        round(2.5 * MS_PER_DAY))
    assert next_task_date("5", 1.0, "", NOW) == NOW_MS + MS_PER_DAY


def test_next_task_date_weekday_mask_uses_js_index():
    """Маска индексируется как JS getDay() (вс=0): суббота → следующий '1'."""
    # «1000000» — воскресенье: от субботы 26.09 это +1 день.
    assert next_task_date("3", 0, "1000000", NOW) == ms(
        datetime(2026, 9, 27, 0, 0, 1, tzinfo=TZ))
    # «0000010» — пятница: от субботы это +6 дней.
    assert next_task_date("3", 0, "0000010", NOW) == ms(
        datetime(2026, 10, 2, 0, 0, 1, tzinfo=TZ))


def test_next_task_date_mask_without_days_and_unknown_mode_raise():
    """Пустая маска и неизвестный repeat_mode — RuntimeError, не тихий пропуск."""
    with pytest.raises(RuntimeError):
        next_task_date("3", 0, "0000000", NOW)
    with pytest.raises(RuntimeError):
        next_task_date("9", 0, "", NOW)


def test_money_reward_uses_plan_and_optional_date_mode():
    """Награда = план · дисциплина / 2; date_mode только если это число."""
    assert money_reward(30, 1.0, float("nan")) == 15.0
    assert money_reward(30, 1.0, 2.0) == 30.0
    assert money_reward(30, 0.5, float("nan")) == 7.5
    assert money_reward(0, 1.0, float("nan")) == 0.0


def test_average_discipline_without_parsable_history_is_one():
    """Нет строк вовсе или нет нужных колонок в шапке → 1.0 (нет данных).

    Пустой, но валидный журнал — не этот случай: там все 30 дней нулевые
    и алгоритм JS честно снижает коэффициент.
    """
    assert average_discipline([], NOW) == 1.0
    assert average_discipline([["id", "title"]], NOW) == 1.0


def test_average_discipline_steady_history_keeps_one():
    """Ровные 10 минут 30 дней подряд — коэффициент не двигается."""
    assert average_discipline(history({ago: 10 for ago in range(30)}),
                              NOW) == 1.0


def test_average_discipline_punishes_fall_below_golden_ratio():
    """Резкое падение вчерашнего и сегодняшнего дня — по −0.01 за день."""
    minutes = {ago: 10 for ago in range(30)}
    minutes[1] = 1
    minutes[0] = 1
    assert average_discipline(history(minutes), NOW) == pytest.approx(0.98)


def test_is_same_local_day():
    """Метка того же локального дня — True, другого дня/пустая — False."""
    assert is_same_local_day(ms(NOW.replace(hour=1)), NOW) is True
    assert is_same_local_day(ms(NOW - timedelta(days=1)), NOW) is False
    assert is_same_local_day(0, NOW) is False
