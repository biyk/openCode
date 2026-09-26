"""Формулы засчёта выполнения задачи (done.md §5, §8, §10).

Чистые вычисления без Google: новый repeat_index, дата следующего
выполнения, коэффициент дисциплины за 30 дней, награда по плану.
Порядок операций и запись в таблицу — в lib/taskflow/done_task.py.
"""

import calendar
import math
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

from lib.taskflow.cells import as_int

MS_PER_DAY = 86_400_000
ONCE_MODE = "5"          # repeat_mode «однократно»: журнал и награда не пишутся
MASK_LEN = 7             # repeat_days_of_week: индекс дня, как в JS getDay() (вс=0)
GOLDEN = 0.6180339887    # порог «просадки» дисциплины (pause.md §5)
DISCIPLINE_WINDOW_DAYS = 30


def repeat_real(old_index: float, days_since: float,
                event_was_new: bool) -> float:
    """Новый repeat_index: среднее старого индекса и дней просрочки (§8)."""
    value = (old_index + days_since) * 0.9 / 2
    return value - 0.1 if event_was_new else value


def _same_day_next_month(now: datetime) -> date:
    """То же число месяца в следующем месяце (31.01 → 28.02)."""
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year,
                                                             now.month + 1)
    last = calendar.monthrange(year, month)[1]
    return datetime(year, month, min(now.day, last)).date()


def _same_day_next_year(now: datetime) -> date:
    """То же число в следующем году (29.02 → 28.02 невисокосного)."""
    last = calendar.monthrange(now.year + 1, now.month)[1]
    return datetime(now.year + 1, now.month, min(now.day, last)).date()


def _next_masked_day(mask: str, now: datetime) -> date:
    """Ближайший день недели из маски repeat_days_of_week (1..7 дней вперёд)."""
    today = (now.weekday() + 1) % MASK_LEN          # Python Mon=0 → JS Sun=0
    padded = (mask or "") + "0" * MASK_LEN
    for offset in range(1, MASK_LEN + 1):
        if padded[(today + offset) % MASK_LEN] == "1":
            return (now + timedelta(days=offset)).date()
    raise RuntimeError("нет рабочих дней в маске repeat_days_of_week")


def next_task_date(mode: str, repeat_index: float, mask: str,
                   now: datetime) -> int:
    """Дата следующего выполнения в мс по repeat_mode (done.md §10)."""
    if mode == "0":                       # каждый день
        day = (now + timedelta(days=1)).date()
    elif mode == "1":                     # каждый месяц
        day = _same_day_next_month(now)
    elif mode == "2":                     # каждый год
        day = _same_day_next_year(now)
    elif mode == "3":                     # по маске дней недели
        day = _next_masked_day(mask, now)
    elif mode in ("5", "6"):              # через repeat_index дней
        return int(now.timestamp() * 1000) + int(round(repeat_index * MS_PER_DAY))
    else:
        raise RuntimeError(f"неизвестный repeat_mode: {mode}")
    at_midnight = datetime.combine(day, dtime(0, 0, 1), tzinfo=now.tzinfo)
    return int(at_midnight.timestamp() * 1000)


def average_discipline(rows: list[list[Any]], now: datetime) -> float:
    """Коэффициент дисциплины за 30 дней (pause.md §5); 1.0 — нет истории."""
    if not rows:
        return 1.0
    header = [str(h).strip() for h in rows[0]]
    if "execution_date" not in header or "execution_time" not in header:
        return 1.0
    di, ti = header.index("execution_date"), header.index("execution_time")
    minutes: dict[str, int] = {}
    for row in rows[1:]:
        if len(row) <= max(di, ti):
            continue
        spent, moment = as_int(row[ti]), as_int(row[di])
        if not spent:
            continue
        day = datetime.fromtimestamp(moment / 1000, now.tzinfo)
        key = day.strftime("%Y-%m-%d")
        minutes[key] = minutes.get(key, 0) + spent
    start, total, count = 1.0, 0, 0
    for i in range(DISCIPLINE_WINDOW_DAYS - 1, -1, -1):
        key = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        current = minutes.get(key, 0)
        if i < DISCIPLINE_WINDOW_DAYS - 1:
            average = total / count if count else 0
            if current <= average * GOLDEN:
                start -= 0.01
            elif current > average:
                start += 0.01
        total += current
        count += 1
    return start


def money_reward(time_spent: int, average: float, date_mode: float) -> float:
    """Награда ✅ — по ПЛАНУ (done.md §8); nan date_mode множитель не даёт."""
    money = time_spent * average / 2
    if math.isfinite(date_mode):
        money *= date_mode
    return money if math.isfinite(money) else 0.0


def is_same_local_day(ms: int, now: datetime) -> bool:
    """Тот же локальный день, что и now (защита от повторного ✅ в тот же день)."""
    if not ms:
        return False
    return datetime.fromtimestamp(ms / 1000, now.tzinfo).date() == now.date()
