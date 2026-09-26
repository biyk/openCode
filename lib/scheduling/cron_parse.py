"""Детерминированный парсер cron-выражений (5 полей, без зависимостей).

Формат классического cron:
    минута  час  день-месяца  месяц  день-недели

Поля: minute 0-59, hour 0-23, dom 1-31, month 1-12, dow 0-7 (0 и 7 —
воскресенье). Поддерживаются `*`, `*/n`, `a`, `a-b`, `a-b/n`, список
`a,b,c`. Месяцы и дни недели можно задавать именами (jan..dec, sun..sat)
в любом регистре.

Специфика cron: если ограничены И день месяца И день недели — поля
работают как ИЛИ (поведение Vixie cron). Полное поле в этой связке
игнорируется.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
DOW_NAMES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}

# Сколько дней вперёд ищется следующее срабатывание (год високосный).
_NEXT_AFTER_DAYS = 1461

_NAME_RE = re.compile(r"[a-zA-Z]+")


def _resolve_names(value: str, names: dict[str, int]) -> str:
    """Заменяет имена (jan/mon) в поле на числа целиком."""
    if not names:
        return value

    def repl(match: "re.Match[str]") -> str:
        key = match.group(0).lower()
        if key not in names:
            raise ValueError(f"неизвестное имя: {match.group(0)}")
        return str(names[key])
    return _NAME_RE.sub(repl, value.lower())


def _parse_field(text: str, lo: int, hi: int,
                 names: dict[str, int]) -> frozenset[int]:
    """Разбирает одно поле cron-выражения в набор допустимых значений."""
    token = _resolve_names(text, names)
    values: set[int] = set()
    for part in token.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"пустое значение в поле: {text!r}")
        step = 1
        body = part
        if "/" in body:
            body, step_text = body.split("/", 1)
            if not body or not step_text.isdigit():
                raise ValueError(f"неверный шаг: {part!r}")
            step = int(step_text)
            if step < 1:
                raise ValueError(f"шаг должен быть >= 1: {part!r}")
        if body == "*":
            start, end = lo, hi
        elif "-" in body:
            start_text, end_text = body.split("-", 1)
            try:
                start, end = int(start_text), int(end_text)
            except ValueError:
                raise ValueError(f"неверный диапазон: {part!r}") from None
        else:
            try:
                start = end = int(body)
            except ValueError:
                raise ValueError(f"не число: {part!r}") from None
        if not (lo <= start <= end <= hi):
            raise ValueError(
                f"значения вне диапазона [{lo}..{hi}]: {part!r}")
        values.update(range(start, end + 1, step))
    return frozenset(values)


def _cron_dow(day: date) -> int:
    """День недели в нотации cron (0 — воскресенье, как и 7)."""
    return (day.weekday() + 1) % 7


def _allowed_times(expr: "CronExpr") -> list[tuple[int, int]]:
    """Отсортированные (час, минута), подходящие выражению."""
    return [(h, m) for h in range(24) if h in expr.hour
            for m in range(60) if m in expr.minute]


class CronExpr:
    """Разобранное cron-выражение: проверка момента и следующего хода."""

    def __init__(self, minute: frozenset[int], hour: frozenset[int],
                 dom: frozenset[int], month: frozenset[int],
                 dow: frozenset[int], source: str) -> None:
        self.source = source
        self.minute = minute
        self.hour = hour
        self.dom = dom
        self.month = month
        self.dow = dow

    def __repr__(self) -> str:
        return f"CronExpr({self.source!r})"

    def _dom_full(self) -> bool:
        return self.dom == frozenset(range(1, 32))

    def _dow_full(self) -> bool:
        return self.dow == frozenset(range(0, 7))

    def _day_matches(self, day: date) -> bool:
        if day.month not in self.month:
            return False
        dom_full = self._dom_full()
        dow_full = self._dow_full()
        dom_ok = day.day in self.dom
        dow_ok = _cron_dow(day) in self.dow
        if dom_full and dow_full:
            return True
        if dom_full:
            return dow_ok
        if dow_full:
            return dom_ok
        return dom_ok or dow_ok

    def matches(self, moment: datetime) -> bool:
        """True, если момент (локальное время) попадает в расписание."""
        if moment.minute not in self.minute:
            return False
        if moment.hour not in self.hour:
            return False
        return self._day_matches(moment.date())

    def next_after(self, moment: datetime) -> datetime:
        """Следующий момент срабатывания строго после moment."""
        start = moment.replace(second=0, microsecond=0) + timedelta(minutes=1)
        times = _allowed_times(self)
        day = start.date()
        for _ in range(_NEXT_AFTER_DAYS):
            if day == start.date():
                for hour, minute in times:
                    if (hour, minute) >= (start.hour, start.minute):
                        return datetime(
                            day.year, day.month, day.day, hour, minute)
            elif self._day_matches(day) and times:
                hour, minute = times[0]
                return datetime(day.year, day.month, day.day, hour, minute)
            day += timedelta(days=1)
        raise ValueError(
            "следующее срабатывание не найдено в течение "
            f"{_NEXT_AFTER_DAYS} дней: {self.source!r}")


def parse_cron(expression: str) -> CronExpr:
    """Разбирает строку «minute hour dom month dow» в CronExpr."""
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError(
            f"ожидается 5 полей, получено {len(fields)}: {expression!r}")
    minute = _parse_field(fields[0], 0, 59, None)
    hour = _parse_field(fields[1], 0, 23, None)
    dom = _parse_field(fields[2], 1, 31, None)
    month = _parse_field(fields[3], 1, 12, MONTH_NAMES)
    dow_raw = _parse_field(fields[4], 0, 7, DOW_NAMES)
    dow = frozenset(0 if value == 7 else value for value in dow_raw)
    return CronExpr(minute, hour, dom, month, dow, expression)
