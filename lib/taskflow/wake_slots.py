"""Окна календаря и перенос задач из окна сна (команда «я проснулся»).

Свободные окна считаем как в restart/calendar.md §5: от начала рабочего
окна до 23:00, шаг не короче 15 минут. Перенос: СОБЫТИЯ ЗАДАЧ (описание с
их task_uuid), начавшиеся внутри окна сна, ставятся на свободные окна
ПОСЛЕ пробуждения в исходном порядке и с той же длительностью. События
«СОН», галочку «Пробуждения», выполненные (`colorId == DONE_COLOR`) и ручные
записи пользователя без uuid задачи не трогаем: подъём засчитывается именно
в момент пробуждения, перенос готовой «галочки» был бы ложным сведением о
выполненном действии, а чужое событие — самопроизвольной его перестановкой.
"""

from datetime import datetime, timedelta
from typing import Any, Optional

from lib.google.google_calendar_events import GoogleCalendarEventsMixin
from lib.google.google_calendar_mutate import DONE_COLOR
from lib.sleep_event import SLEEP_TITLE_RE

# Параметры рабочего дня (calendar.md §5): конец 23:00, мин. слот 15 мин.
MIN_SLOT_MIN = 15
WORK_END_HOUR = 23

# Задача «Пробуждение» в real_life_tasks (её uuid). Её событие-«галочка»
# ставится на интервал до момента подъёма, то есть всегда попадает в окно
# сна, — и переносу не подлежит: это запись о уже выполненном действии.
WAKE_TASK_UUID = "f29ef6e3-f1f9-418c-a657-49ffa5dc9497"


def event_datetime(raw: Any) -> Optional[datetime]:
    """start/end события → aware datetime; «весь день» (дата без T) → None."""
    if not raw or "T" not in str(raw):
        return None
    dt = GoogleCalendarEventsMixin._parse_event_datetime(str(raw))
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.astimezone()


def is_sleep_event(summary: Any) -> bool:
    """Заголовок события — «СОН» (то же правило, что у команды сна)."""
    return bool(SLEEP_TITLE_RE.search(str(summary or "")))


def compute_free_slots(events: list[dict], work_start: datetime,
                       work_end: datetime,
                       min_slot: int = MIN_SLOT_MIN) -> list[dict]:
    """Окна [work_start, work_end], свободные от событий (duration в минутах).

    Как getFreeSlots в JS: сортируем занятые интервалы, идём курсором и
    собираем дырки не короче min_slot. Каждый слот: start, duration (float).
    """
    busy = []
    for ev in events:
        start = event_datetime(ev.get("start"))
        end = event_datetime(ev.get("end"))
        if start is None or end is None:
            continue
        busy.append((start, end))
    busy.sort(key=lambda pair: pair[0])

    free: list[dict] = []
    cursor = work_start
    for b_start, b_end in busy:
        if b_start > cursor:
            gap = (b_start - cursor).total_seconds() / 60
            if gap >= min_slot:
                free.append({"start": cursor, "duration": gap})
        cursor = max(cursor, b_end)
    if cursor < work_end:
        gap = (work_end - cursor).total_seconds() / 60
        if gap >= min_slot:
            free.append({"start": cursor, "duration": gap})
    return free


def _consume_slot(free: list[dict], idx: int, duration: float,
                  new_end: datetime) -> None:
    """«Съедает» окно: остаток < min_slot — удаляем, иначе сдвигаем начало."""
    rest = free[idx]["duration"] - duration
    if rest < MIN_SLOT_MIN:
        free.pop(idx)
    else:
        free[idx] = {"start": new_end, "duration": rest}


def _is_known_task(desc: str, known_uuids: Optional[set]) -> bool:
    """Описание события содержит uuid задачи из real_life_tasks.

    Пользовательские события без uuid («Игры на компе») из окна сна НЕ
    уезжают: переносим только запланированные записи самих задач — их
    описание всегда содержит task_uuid (так пишет `fill_calendar`).
    """
    if not desc or not known_uuids:
        return False
    return any(u and u in desc for u in known_uuids)


def reschedule_sleep_events(google: Any, events: list[dict],
                            sleep_start: datetime,
                            wake_now: datetime,
                            known_uuids: Optional[set] = None
                            ) -> tuple[int, list[dict]]:
    """Переносит события ЗАДАЧ, начавшиеся в окне [sleep_start, wake_now), позже.

    Двигаются только события, чьё описание содержит uuid из `known_uuids`
    (множество task_uuid стро `real_life_tasks`): в исходном порядке, на
    первое свободное окно после пробуждения достаточной длительности, с
    сохранением длительности. События «СОН», галочку «Пробуждения», все
    выполненные (`colorId == DONE_COLOR`) и ВСЕ прочие события без uuid
    задачи (напр. ручная «Игры на компе») не трогает: перенос завершённой
    задачи был бы ложным сведением о выполненном, а чужое событие —
    самопроизвольной его перестановкой. Возвращает (число_переносов,
    обновлённый список событий — для последующего автозаполнения).
    """
    day_end = wake_now.replace(hour=WORK_END_HOUR, minute=0,
                               second=0, microsecond=0)
    caught: list[tuple[datetime, float, dict]] = []
    for ev in events:
        if is_sleep_event(ev.get("summary")):
            continue
        desc = str(ev.get("description") or "").lower()
        if WAKE_TASK_UUID in desc:
            continue  # галочка «Пробуждения» остаётся на своём месте
        if str(ev.get("colorId") or "") == DONE_COLOR:
            continue  # выполненные (colorId=7) не двигаем — это уже факт
        if not _is_known_task(desc, known_uuids):
            continue  # не задача из таблицы (напр. «Игры на компе») — стоит
        start = event_datetime(ev.get("start"))
        end = event_datetime(ev.get("end"))
        if start is None or end is None:
            continue
        if sleep_start <= start < wake_now:
            caught.append((start, (end - start).total_seconds() / 60, ev))
    caught.sort(key=lambda item: item[0])
    if not caught:
        return 0, events

    updated = [dict(ev) for ev in events]
    by_id = {ev.get("id"): ev for ev in updated}
    free = compute_free_slots(events, wake_now, day_end)
    moved = 0
    for _, duration, ev in caught:
        idx = next((i for i, s in enumerate(free)
                    if s["duration"] >= duration), None)
        if idx is None:
            continue
        slot_start = free[idx]["start"]
        slot_end = slot_start + timedelta(minutes=duration)
        if not google.move_event(ev["id"], slot_start, slot_end):
            continue
        target = by_id.get(ev.get("id"))
        if target is not None:
            target["start"] = slot_start.isoformat()
            target["end"] = slot_end.isoformat()
        moved += 1
        _consume_slot(free, idx, duration, slot_end)
    return moved, updated
