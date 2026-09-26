"""Автозаполнение календаря задачами на остаток дня (restart/calendar.md).

Эквивалент кнопки «Заполнить календарь»: раскладывает подлежащие задачи
real_life_tasks по свободным окнам от «сейчас» до 23:00 по приоритету,
идемпотентно (не дублирует уже запланированное) и БЕЗ записи в Таблицы —
единственная мутация это events.insert в Calendar.
"""

import math
from datetime import datetime, timedelta
from typing import Any

from lib.taskflow.cells import as_float, as_int
from lib.taskflow.wake_slots import (
    MIN_SLOT_MIN, WORK_END_HOUR, compute_free_slots)


def task_sort_key(task: dict, now: datetime) -> float:
    """Приоритет как taskSort в JS: меньшее значение планируется раньше.

    task_sort − daysDiff(task_date) · break_multiplier: давно просроченные
    (и с большим штрафом за пропуски) задачи подъезжают наверх.
    """
    task_ms = as_int(task.get("task_date"))
    if not task_ms:
        days = 0
    else:
        task_dt = datetime.fromtimestamp(task_ms / 1000, tz=now.tzinfo)
        days = math.floor((now - task_dt).total_seconds() / 86400)
    return (as_float(task.get("task_sort"))
            - days * as_float(task.get("break_multiplier")))


def _is_candidate(task: dict, now_ms: int) -> bool:
    """Подлежит автоплану: не тех. строка, срок наступил, есть длительность."""
    title = str(task.get("task_title") or "")
    if "task_title" in title:
        return False
    if as_int(task.get("task_date")) >= now_ms:
        return False
    return as_int(task.get("task_time")) > 0


def fill_calendar(google: Any, sheet: Any, events: list[dict],
                  now: datetime) -> int:
    """Ставит подлежащие задачи в свободные окна до 23:00. Возвращает число.

    events — события дня ПОСЛЕ переноса из окна сна (чтобы окна уже учли
    переставленные задачи). В Таблицы не пишет ничего (calendar.md §14).
    """
    now_ms = int(now.timestamp() * 1000)
    day_end = now.replace(hour=WORK_END_HOUR, minute=0,
                          second=0, microsecond=0)
    free = compute_free_slots(events, now, day_end)
    # Описания событий, уже лежащих в календаре (+ что только что поставили):
    # по ним режем дубли и конфликты excludes (подстрочный поиск, как в JS).
    described = [str(ev.get("description") or "") for ev in events]

    tasks = [t for t in sheet.read_all_tasks() if _is_candidate(t, now_ms)]
    tasks.sort(key=lambda t: task_sort_key(t, now))

    placed = 0
    for task in tasks:
        uuid = str(task.get("task_uuid") or "").strip()
        if not uuid or any(uuid in d for d in described):
            continue  # уже запланирована/выполнена сегодня — пропускаем
        excludes = str(task.get("excludes") or "")
        if excludes and any(d and d in excludes for d in described):
            continue  # конфликт по excludes — «не сегодня»
        duration = as_int(task.get("task_time"))
        idx = next((i for i, s in enumerate(free)
                    if s["duration"] >= duration), None)
        if idx is None:
            continue  # некуда втиснуть
        slot_start = free[idx]["start"]
        slot_end = slot_start + timedelta(minutes=duration)
        if not google.create_task_event(str(task.get("task_title") or ""),
                                        uuid, slot_start, slot_end):
            continue
        described.append(uuid)
        placed += 1
        rest = free[idx]["duration"] - duration
        if rest < MIN_SLOT_MIN:
            free.pop(idx)
        else:
            free[idx] = {"start": slot_end, "duration": rest}
    return placed
