# TOOLTIP: Дыры между синими задачами календаря, цвет и маркер развлечений
"""Поиск «дыр» календаря для заполнения развлечениями.

Дыра — промежуток между двумя соседними событиями colorId=7 (задачи, помеченные
«сделано»), даже если между ними стоят события других цветов. Окно ограничено
снизу пробуждением (конец сегодняшнего «СОН»), сверху — началом последней
синей задачи: всё, что мы заполняем, уже в прошедшем времени, и автоплан
туда ничего не пишет.

Своё событие помечаем токеном в description. Развлечение НЕ синее, поэтому
после вставки соседями по цвету остаются те же две задачи и та же дыра —
без маркера одна и та же дыра закрывалась бы каждый цикл, а деньги списывались
бы повторно. Исполнение — в lib/taskflow/fun_fill.py.
"""

from datetime import datetime
from typing import Any, Optional

from lib.core.tuning import FUN_COLOR_EVENT_TITLE, FUN_FALLBACK_COLOR, FUN_MIN_GAP_MIN
from lib.google.google_calendar_mutate import DONE_COLOR
from lib.taskflow.wake_slots import event_datetime, is_sleep_event

# Токен в description события-развлечения: по нему дыра считается закрытой.
FUN_MARKER = "fun_hole"


def _norm(text: Any) -> str:
    """Заголовок для сравнения: регистр, обрамляющие пробелы, «ё»."""
    return " ".join(str(text or "").casefold().replace("ё", "е").split())


def _span(ev: dict) -> Optional[tuple[datetime, datetime]]:
    """(начало, конец) события; None для «весь день» и для пустых интервалов."""
    start = event_datetime(ev.get("start"))
    end = event_datetime(ev.get("end"))
    if start is None or end is None or end <= start:
        return None
    return start, end


def is_fun_event(ev: dict) -> bool:
    """Событие-развлечение создано нами (маркер в описании)."""
    return FUN_MARKER in str(ev.get("description") or "")


def fun_color(events: list[dict]) -> str:
    """colorId мероприятия-донора (самого свежего из найденных).

    Мероприятие разовое, поэтому смотрим всё загруженное окно lookback;
    не нашли ничего — FUN_FALLBACK_COLOR.
    """
    wanted = _norm(FUN_COLOR_EVENT_TITLE)
    best: Optional[tuple[datetime, str]] = None
    for ev in events:
        if _norm(ev.get("summary")) != wanted:
            continue
        color = str(ev.get("colorId") or "").strip()
        span = _span(ev)
        if not color or span is None:
            continue
        if best is None or span[0] > best[0]:
            best = (span[0], color)
    return best[1] if best else FUN_FALLBACK_COLOR


def done_spans(events: list[dict], since: datetime) -> list[tuple[datetime, datetime]]:
    """Интервалы синих задач, начавшихся не раньше `since`, по порядку."""
    out = []
    for ev in events:
        if str(ev.get("colorId") or "").strip() != DONE_COLOR:
            continue
        span = _span(ev)
        if span is not None and span[0] >= since:
            out.append(span)
    out.sort(key=lambda pair: pair[0])
    return out


def wake_edge(events: list[dict], now: datetime) -> datetime:
    """Левый край окна: конец сегодняшнего «СОН» (начало дня, если его нет)."""
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    edge = day_start
    for ev in events:
        if not is_sleep_event(ev.get("summary")):
            continue
        span = _span(ev)
        if span is not None and span[1] > edge and span[0] >= day_start:
            edge = span[1]
    return edge


def _covered(funs: list[tuple[datetime, datetime]],
             lo: datetime, hi: datetime) -> bool:
    """Есть ли внутри промежутка [lo, hi] уже созданное развлечение."""
    return any(start < hi and end > lo for start, end in funs)


def find_holes(events: list[dict], now: datetime,
               min_gap: float = FUN_MIN_GAP_MIN) -> list[dict]:
    """Дыры между соседними синими задачами сегодня (start, end, minutes).

    Пересекающиеся/вложенные синие события (галочки ставятся задним числом)
    сворачиваются бегущим максимумом конца, поэтому промежуток никогда не
    бывает отрицательным. Дыра после последней синей задачи не возвращается:
    её правого края нет, и там ещё возможны плановые события.
    """
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    spans = done_spans(events, day_start)
    if len(spans) < 2:
        return []
    funs = []
    for ev in events:
        if is_fun_event(ev):
            span = _span(ev)
            if span is not None:
                funs.append(span)
    lo = wake_edge(events, now)
    cursor = max(lo, spans[0][1])
    holes: list[dict] = []
    for start, end in spans[1:]:
        gap = (start - cursor).total_seconds() / 60.0
        if gap >= min_gap and not _covered(funs, cursor, start):
            holes.append({"start": cursor, "end": start, "minutes": gap})
        cursor = max(cursor, end)
    return holes
