"""Эквивалент клика ✅ («засчитать выполнение по плану») из Python.

Цикл тот же, что у ⏹ (done.md §1), но задача не запущена: длительность
берётся из плана (колонка B), и сама колонка B остаётся прежней (§2).
Нужен команде «я проснулся» для задачи «Пробуждение».

CLI: `python -m lib.taskflow.done_task <task_uuid>`. Коды выхода: 0 —
засчитано (или уже было засчитано сегодня), 1 — задача не найдена или
запрос не прошёл.
"""

import sys
import uuid as uuidlib
from datetime import datetime
from typing import Any, Optional

from lib.taskflow.cells import as_float, as_int
from lib.taskflow.done_calc import (
    MS_PER_DAY,
    ONCE_MODE,
    average_discipline,
    is_same_local_day,
    money_reward,
    next_task_date,
    repeat_real,
)
from lib.taskflow.real_life_sheet import COLS, RealLifeSheet


def _done_row(row: list[Any], ri_new: float, task_date: int, money: float,
              now_ms: int, event_was_new: bool) -> list[Any]:
    """Строка A:T после ✅: колонки B (план) и G (start_date) не меняем (§4)."""
    out = list(row)
    out[COLS["task_date"]] = task_date
    out[COLS["repeat_index"]] = ri_new
    out[COLS["money_reward"]] = money
    out[COLS["task_finish_date"]] = 0
    out[COLS["number_of_executions"]] = as_int(row[COLS["number_of_executions"]]) + 1
    out[COLS["last_execution"]] = now_ms
    if event_was_new:
        out[COLS["break_multiplier"]] = as_float(row[COLS["break_multiplier"]]) + 1
        out[COLS["task_sort"]] = as_float(row[COLS["task_sort"]]) - 0.02
    return out


def _execution_row(task_uuid: str, row: list[Any], now: datetime, now_ms: int,
                   time_spent: int, money: float) -> list[str]:
    """Строка журнала task_executions: execution_time — ПЛАН, не факт (§5)."""
    return [str(uuidlib.uuid4()), str(now_ms), str(time_spent), str(money),
            row[COLS["task_title"]], task_uuid, now.strftime("%d.%m.%Y")]


def mark_task_done(task_uuid: str, api: Optional[Any] = None,
                   now: Optional[datetime] = None,
                   once_per_day: bool = True) -> dict:
    """✅ по task_uuid: галочка в календаре, строка A:T, журнал, награда.

    api/now инжектят тесты. RuntimeError — задача запущена: тогда нужен
    ⏹ с фактической длительностью, а не ✅ по плану (done.md §3).
    """
    api = api or RealLifeSheet()
    now = now or datetime.now().astimezone()
    found = api.find_task_row(task_uuid)
    if found is None:
        return {"ok": False,
                "error": f"задача {task_uuid} не найдена в таблице"}
    row_idx, row = found
    title = str(row[COLS["task_title"]] or "").strip()
    if as_int(row[COLS["start_date"]]) != 0:
        raise RuntimeError("задача запущена — ожидается ⏹, а не ✅")
    now_ms = int(now.timestamp() * 1000)
    last_ms = as_int(row[COLS["last_execution"]])
    if once_per_day and is_same_local_day(last_ms, now):
        return {"ok": True, "skipped": True, "title": title,
                "reason": "уже засчитано сегодня"}

    # ✅: длительность по плану, колонку B не трогаем (§2, §8)
    time_spent = as_int(row[COLS["task_time"]])
    event = api.find_done_event(task_uuid, now)
    was_new = api.upsert_done_event(
        (event or {}).get("summary") or title, task_uuid, time_spent, now,
        event_id=(event or {}).get("id"))

    from_ms = last_ms or as_int(row[COLS["task_date"]])
    ri_new = repeat_real(as_float(row[COLS["repeat_index"]], 1.0) or 1.0,
                         (now_ms - from_ms) / MS_PER_DAY, was_new)
    mode = str(row[COLS["repeat_mode"]]).strip()
    task_date = next_task_date(mode, ri_new,
                               str(row[COLS["repeat_days_of_week"]] or ""), now)
    money = money_reward(time_spent,
                         average_discipline(api.execution_rows(), now),
                         as_float(row[COLS["date_mode"]], float("nan")))

    api.write_task_row(row_idx, _done_row(row, ri_new, task_date, money,
                                          now_ms, was_new))
    if mode != ONCE_MODE:
        api.append_execution(
            _execution_row(task_uuid, row, now, now_ms, time_spent, money))
        api.add_hero_money(money)
    return {"ok": True, "title": title, "uuid": task_uuid, "row": row_idx,
            "time_spent": time_spent, "money": money,
            "task_date_ms": task_date, "event_was_new": was_new}


def _main(argv: Optional[list[str]] = None) -> int:
    """CLI: `python -m lib.taskflow.done_task <task_uuid>`. 0 — засчитано."""
    args = [a for a in (sys.argv[1:] if argv is None else argv) if a.strip()]
    if not args:
        print("Укажи task_uuid: python -m lib.taskflow.done_task <uuid>")
        return 1
    try:
        result = mark_task_done(args[0])
    except Exception as e:  # нет токена/сети/неизвестный repeat_mode
        print(f"[done] ошибка засчёта: {e}")
        return 1
    if result.get("skipped"):
        print(f"[done] «{result['title']}» уже засчитана сегодня")
        return 0
    if not result.get("ok"):
        print(f"[done] {result['error']}")
        return 1
    print(f"✅ «{result['title']}» засчитана по плану: "
          f"{result['time_spent']} мин, награда {result['money']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
