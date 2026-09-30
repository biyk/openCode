# TOOLTIP: Время-зависимый выбор задач для предложения (по событиям календаря)
"""Чистый выбор «что предложить» по времени суток.

Строки real_life_tasks не хранят время дня — оно берётся из сегодняшних
событий календаря, привязанных к задаче по task_uuid (в description).
Учитываются только незапущенные задачи (start_date = 0), а события-«галочки»
(colorId = 7, уже засчитанное выполнение) не предлагаются. Сеть не трогаем:
события, строки и `now` инжектят вызывающий код и тесты.

Две ручки: `current_or_next` — идущая сейчас задача (а если ничего не идёт,
ближайшая следующая) для голосового вопроса; `upcoming_titles` — до трёх
задач, которые можно начать от текущего момента до «СОН», для кнопок в
Telegram. Сборкой занимается `lib/core/task_monitor.py`.
"""

import re
from datetime import datetime
from typing import Optional

from lib.google.google_calendar_mutate import DONE_COLOR
from lib.taskflow.cells import as_int
from lib.taskflow.task_check import suggest_idle_task
from lib.taskflow.wake_slots import event_datetime, is_sleep_event

# Сколько задач показывать кнопками (предложение «начать сейчас»).
OFFER_LIMIT = 3

# task_uuid в описании события (тот же формат, что в lib.task_start).
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE)


def _span(ev: dict) -> Optional[tuple[datetime, datetime]]:
    """(начало, конец) события; None, если времени нет (например, «весь день»)."""
    start = event_datetime(ev.get("start"))
    if start is None:
        return None
    end = event_datetime(ev.get("end"))
    return start, (end if end is not None else start)


def _unstarted_titles(rows: list[dict]) -> dict[str, str]:
    """{uuid: заголовок} незапущенных (start_date = 0) задач с непустым именем."""
    out: dict[str, str] = {}
    for row in rows:
        if as_int(row.get("start_date")) > 0:
            continue
        title = str(row.get("task_title") or "").strip()
        uuid = str(row.get("task_uuid") or "").strip().lower()
        if title and uuid:
            out[uuid] = title
    return out


def _candidates(rows: list[dict], events: list[dict]) -> list[dict]:
    """Незапущенные задачи с сегодняшним плановым событием, по началу."""
    unstarted = _unstarted_titles(rows)
    cands = []
    for ev in events or []:
        if str(ev.get("colorId") or "").strip() == DONE_COLOR:
            continue                        # галочка засчитанного выполнения
        match = _UUID_RE.search(ev.get("description") or "")
        if not match:
            continue
        uuid = match.group(0).lower()
        title = unstarted.get(uuid)
        if title is None:
            continue                        # задачи нет среди незапущенных
        span = _span(ev)
        if span is None:
            continue
        cands.append({"title": title, "uuid": uuid,
                      "start": span[0], "end": span[1]})
    cands.sort(key=lambda c: c["start"])
    return cands


def sleep_edge(events: list[dict], now: datetime) -> Optional[datetime]:
    """Начало ближайшего после `now` «СОН» — верхняя граница «можно начать».

    None — сегодняшнего отхода ко сну в окне нет (тогда не ограничиваем).
    """
    best: Optional[datetime] = None
    for ev in events or []:
        if not is_sleep_event(ev.get("summary")):
            continue
        start = event_datetime(ev.get("start"))
        if start is None or start < now:
            continue
        if best is None or start < best:
            best = start
    return best


def upcoming_titles(rows: list[dict], events: list[dict], now: datetime,
                    until: Optional[datetime] = None,
                    limit: int = OFFER_LIMIT) -> list[str]:
    """Заголовки незапущенных задач от `now` (ещё не закончившихся) до `until`.

    Идущая сейчас (началась до `now`, но ещё не завершилась) попадает первой:
    её начало раньше. `until` — начало сна; None — не ограничиваем. По одной
    задаче с одинаковым uuid (повторные слоты не дублируем).
    """
    seen: set[str] = set()
    out: list[str] = []
    for cand in _candidates(rows, events):
        if cand["end"] < now:               # уже отработало сегодня
            continue
        if until is not None and cand["start"] >= until:
            continue                        # позже отхода ко сну
        if cand["uuid"] in seen:
            continue
        seen.add(cand["uuid"])
        out.append(cand["title"])
        if limit and len(out) >= limit:
            break
    return out


def current_or_next(rows: list[dict], events: list[dict],
                    now: datetime) -> Optional[str]:
    """Идущая сейчас задача; если ничего не идёт — ближайшая следующая."""
    titles = upcoming_titles(rows, events, now, until=None, limit=1)
    return titles[0] if titles else None


def idle_offer(rows: list[dict], events: Optional[list[dict]],
               now: datetime,
               limit: int = OFFER_LIMIT) -> tuple[Optional[str], list[str]]:
    """(что предложить вслух, до `limit` названий для кнопок Telegram).

    Без событий (календарь не подключён или не прочитался) — откат к первой
    незапущенной строке таблицы и пустому списку кнопок (голосовой вопрос
    работает как раньше).
    """
    if not events:
        return suggest_idle_task(rows), []
    voice = current_or_next(rows, events, now)
    titles = upcoming_titles(rows, events, now,
                             until=sleep_edge(events, now), limit=limit)
    return voice, titles


__all__ = ["OFFER_LIMIT", "sleep_edge", "upcoming_titles", "current_or_next",
           "idle_offer"]
