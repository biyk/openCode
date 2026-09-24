"""Юнит-тесты парсера cron-выражений (lib.cron_parse)."""

from datetime import datetime

import pytest

from lib.cron_parse import parse_cron

D = datetime


def test_every_minute_matches_all():
    expr = parse_cron("* * * * *")
    assert expr.matches(D(2026, 9, 24, 21, 0))
    assert expr.matches(D(2026, 9, 24, 21, 59))
    assert expr.matches(D(2026, 9, 24, 0, 0))


def test_hourly_at_zero_minute():
    expr = parse_cron("0 * * * *")
    assert expr.matches(D(2026, 9, 24, 21, 0))
    assert not expr.matches(D(2026, 9, 24, 21, 1))


def test_step_every_five_minutes():
    expr = parse_cron("*/5 * * * *")
    assert expr.matches(D(2026, 9, 24, 21, 5))
    assert expr.matches(D(2026, 9, 24, 21, 30))
    assert not expr.matches(D(2026, 9, 24, 21, 7))


def test_range_and_step():
    expr = parse_cron("1-10/3 * * * *")
    for minute in (1, 4, 7, 10):
        assert expr.matches(D(2026, 9, 24, 12, minute))
    assert not expr.matches(D(2026, 9, 24, 12, 2))


def test_list():
    expr = parse_cron("0,30 * * * *")
    assert expr.matches(D(2026, 9, 24, 21, 0))
    assert expr.matches(D(2026, 9, 24, 21, 30))
    assert not expr.matches(D(2026, 9, 24, 21, 15))


def test_month_and_dow_names():
    expr = parse_cron("0 9 * jan mon")
    assert expr.matches(D(2026, 1, 5, 9, 0))   # понедельник января
    assert not expr.matches(D(2026, 1, 6, 9, 0))  # вторник
    assert not expr.matches(D(2026, 2, 2, 9, 0))  # понедельник февраля


def test_dow_7_equals_0():
    sunday = parse_cron("0 0 * * 0")
    sunday_7 = parse_cron("0 0 * * 7")
    assert sunday.matches(D(2026, 9, 20, 0, 0))
    assert sunday_7.matches(D(2026, 9, 20, 0, 0))
    assert not sunday.matches(D(2026, 9, 21, 0, 0))


def test_dom_or_dow_rule():
    """Ограничны и dom, и dow — срабатывает любое (правило Vixie)."""
    expr = parse_cron("0 0 13 * fri")
    assert expr.matches(D(2026, 1, 13, 0, 0))   # 13-е, вторник
    assert expr.matches(D(2026, 2, 13, 0, 0))   # пятница 13
    assert expr.matches(D(2026, 2, 20, 0, 0))   # пятница, не 13-е
    assert not expr.matches(D(2026, 2, 14, 0, 0))  # суббота, не 13-е


def test_single_day_matches_dom_only():
    expr = parse_cron("0 0 15 * *")
    assert expr.matches(D(2026, 9, 15, 0, 0))
    assert not expr.matches(D(2026, 9, 24, 0, 0))


def test_next_after_step():
    expr = parse_cron("*/5 * * * *")
    assert expr.next_after(D(2026, 9, 24, 21, 3, 30)) == D(2026, 9, 24, 21, 5)
    assert expr.next_after(D(2026, 9, 24, 21, 5, 0)) == D(2026, 9, 24, 21, 10)


def test_next_after_next_day():
    expr = parse_cron("0 9 * * *")
    assert expr.next_after(D(2026, 9, 24, 21, 0)) == D(2026, 9, 25, 9, 0)


def test_next_after_across_leap_year():
    expr = parse_cron("0 0 29 feb *")
    assert expr.next_after(D(2026, 3, 1)) == D(2028, 2, 29, 0, 0)


@pytest.mark.parametrize("expression", [
    "5 * * *",
    "",
    "60 * * * *",
    "* * 32 * *",
    "* * * 13 *",
    "* * * * 8",
    "*/0 * * * *",
    "5-1 * * * *",
    "x * * * *",
    "* * * foo *",
    "* * * * * *",
])
def test_invalid_expressions(expression):
    with pytest.raises(ValueError):
        parse_cron(expression)
