"""Эквивалент клика ⏹ («остановить и засчитать») из Python (stop.md).

В отличие от ✅ (done_task.py) задача запущена: считаем фактическую
длительность от start_date (колонка G), усредняем план с фактом в
колонке B, награда и журнал — по факту. Колонка O на выходе = 0
(в отличие от ⏸). Цикл операций идентичен done_task.py.

CLI: `python -m lib.taskflow.stop_task <task_uuid>`. Коды выхода: 0 —
засчитано, 1 — задача не найдена/не запущена или запрос не прошёл.
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
    average_task_time,
    elapsed_minutes,
    money_reward,
    next_task_date,
    repeat_real,
)
from lib.taskflow.real_life_sheet import COLS, RealLifeSheet


def _stop_row(row: list[Any], new_time: int, ri_new: float, task_date: int,
              money: float, now_ms: int, event_was_new: bool) -> list[Any]:
    """Строка A:T после ⏹: колонки B/G меняются, O обнуляется (§2.1, §8)."""
    out = list(row)
    out[COLS["task_time"]] = new_time
    out[COLS["start_date"]] = 0
    out[COLS["task_date"]] = task_date
    out[COLS["repeat_index"]] = ri_new
    out[COLS["money_reward"]] = money
    out[COLS["task_finish_date"]] = 0
    out[COLS["number_of_executions"]] = as_int(
        row[COLS["number_of_executions"]]) + 1
    out[COLS["last_execution"]] = now_ms
    if event_was_new:
        out[COLS["break_multiplier"]] = as_float(
            row[COLS["break_multiplier"]]) + 1
        out[COLS["task_sort"]] = as_float(row[COLS["task_sort"]]) - 0.02
    return out


def _execution_row(task_uuid: str, row: list[Any], now: datetime,
                   now_ms: int, elapsed: int, money: float) -> list[str]:
    """Строка журнала task_executions: execution_time — ФАКТ (stop.md §2.2)."""
    return [str(uuidlib.uuid4()), str(now_ms), str(elapsed), str(money),
            row[COLS["task_title"]], task_uuid, now.strftime("%d.%m.%Y")]


def stop_task(task_uuid: str, api: Optional[Any] = None,
              now: Optional[datetime] = None) -> dict:
    """⏹ по task_uuid: требует запущенной задачи, считает elapsed (§3–§9).

    api/now инжектят тесты. RuntimeError — задача НЕ запущена: тогда
    нужен ✅ по плану (done.md §3), а не ⏹ с фактической длительностью.
    """
    api = api or RealLifeSheet()
    now = now or datetime.now().astimezone()
    found = api.find_task_row(task_uuid)
    if found is None:
        return {"ok": False,
                "error": f"задача {task_uuid} не найдена в таблице"}
    row_idx, row = found
    title = str(row[COLS["task_title"]] or "").strip()
    start_ms = as_int(row[COLS["start_date"]])
    if start_ms == 0:
        raise RuntimeError("задача не запущена — ожидается ✅, а не ⏹")
    now_ms = int(now.timestamp() * 1000)

    # ⏹: длительность по факту, план усредняется с фактом (§4.1)
    elapsed = elapsed_minutes(start_ms, now_ms)
    new_time = average_task_time(as_int(row[COLS["task_time"]]), elapsed)
    event = api.find_done_event(task_uuid, now)
    was_new = api.upsert_done_event(
        (event or {}).get("summary") or title, task_uuid, elapsed, now,
        event_id=(event or {}).get("id"))

    from_ms = as_int(row[COLS["last_execution"]]) or as_int(
        row[COLS["task_date"]])
    ri_new = repeat_real(as_float(row[COLS["repeat_index"]], 1.0) or 1.0,
                         (now_ms - from_ms) / MS_PER_DAY, was_new)
    mode = str(row[COLS["repeat_mode"]]).strip()
    task_date = next_task_date(mode, ri_new,
                               str(row[COLS["repeat_days_of_week"]] or ""),
                               now)
    money = money_reward(elapsed,
                         average_discipline(api.execution_rows(), now),
                         as_float(row[COLS["date_mode"]], float("nan")))

    api.write_task_row(row_idx, _stop_row(row, new_time, ri_new, task_date,
                                          money, now_ms, was_new))
    if mode != ONCE_MODE:
        api.append_execution(
            _execution_row(task_uuid, row, now, now_ms, elapsed, money))
        api.add_hero_money(money)
    return {"ok": True, "title": title, "uuid": task_uuid, "row": row_idx,
            "elapsed_minutes": elapsed, "task_time": new_time,
            "money": money, "task_date_ms": task_date,
            "event_was_new": was_new}


def _main(argv: Optional[list[str]] = None) -> int:
    """CLI: `python -m lib.taskflow.stop_task <task_uuid>`. 0 — засчитано."""
    args = [a for a in (sys.argv[1:] if argv is None else argv) if a.strip()]
    if not args:
        print("Укажи task_uuid: python -m lib.taskflow.stop_task <uuid>")
        return 1
    try:
        result = stop_task(args[0])
    except Exception as e:  # нет токена/сети/не запущена/неизвестный режим
        print(f"[stop] ошибка завершения: {e}")
        return 1
    if not result.get("ok"):
        print(f"[stop] {result['error']}")
        return 1
    print(f"⏹ «{result['title']}» засчитана по факту: "
          f"{result['elapsed_minutes']} мин, награда {result['money']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
