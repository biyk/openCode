# TOOLTIP: Дыры между синими задачами календаря, цвет и маркер развлечений
"""Поиск «дыр» календаря для заполнения развлечениями.

Дыра — промежуток между двумя соседними событиями colorId=7 (задачи, помеченные
«сделано»), даже если между ними стоят события других цветов. Окно ограничено
снизу пробуждением (конец последнего завершившегося «СОН»), сверху — началом
последней синей задачи: всё, что мы заполняем, уже в прошедшем времени, и
автоплан туда ничего не пишет.

Последняя граница дня — начало «СНА», когда оно уже наступило: со сном время до
него тоже стало прошлым, поэтому хвост дня (от конца последней задачи до сна)
считается дырой и закрывается (§4.4). Пока сон не начался, хвост не трогаем —
туда ещё пишет автоплан.

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


def wake_edge(events: list[dict], now: datetime,
              day_start: Optional[datetime] = None) -> datetime:
    """Левый край окна: конец последнего «СОН», закончившегося к `now`.

    Идущий сейчас сон пробуждением не считается: его конец завтра, край окна
    уехал бы в будущее и дыр не осталось бы вовсе (вечер, §4.4).
    """
    left = day_start or now.replace(hour=0, minute=0, second=0, microsecond=0)
    edge = left
    for ev in events:
        if not is_sleep_event(ev.get("summary")):
            continue
        span = _span(ev)
        if span is None or span[1] > now or span[1] < left:
            continue
        if span[1] > edge:
            edge = span[1]
    return edge


def sleep_start(events: list[dict], now: datetime) -> Optional[datetime]:
    """Начало «СОН», который идёт прямо сейчас — последняя граница дня.

    None — сон ещё не наступил (его начало в будущем: там автоплан) или уже
    завершился (день закрыт этим же кодом раньше). Берётся самое свежее из
    начавшихся: команда сна сдвигает начало «СНА» на текущий момент.
    """
    best: Optional[datetime] = None
    for ev in events:
        if not is_sleep_event(ev.get("summary")):
            continue
        span = _span(ev)
        if span is None or span[0] > now or span[1] <= now:
            continue
        if best is None or span[0] > best:
            best = span[0]
    return best


def _did_tasks(events: list[dict], since: datetime) -> bool:
    """Есть в окне синяя галочка именно ЗАДАЧИ (события «СОН» — не задача).

    Нужно для хвоста дня: без единой выполненной задачи дыра «весь день»
    списала бы hero_money за время, которого в календаре не было.
    """
    for ev in events:
        if str(ev.get("colorId") or "").strip() != DONE_COLOR:
            continue
        if is_sleep_event(ev.get("summary")):
            continue
        span = _span(ev)
        if span is not None and span[0] >= since:
            return True
    return False


def _covered(funs: list[tuple[datetime, datetime]],
             lo: datetime, hi: datetime) -> bool:
    """Есть ли внутри промежутка [lo, hi] уже созданное развлечение."""
    return any(start < hi and end > lo for start, end in funs)


def find_holes(events: list[dict], now: datetime,
               min_gap: float = FUN_MIN_GAP_MIN) -> list[dict]:
    """Дыры дня (start, end, minutes) — всё строго в прошедшем времени.

    Пересекающиеся/вложенные синие события (галочки ставятся задним числом)
    сворачиваются бегущим максимумом конца, поэтому промежуток никогда не
    бывает отрицательным. Дыра после последней синей задачи появляется только
    со сном: его начало — правый край хвоста дня (§4.4).
    """
    bound = sleep_start(events, now)
    day_start = (bound or now).replace(hour=0, minute=0, second=0,
                                       microsecond=0)
    spans = done_spans(events, day_start)
    if not spans:
        return []
    funs = []
    for ev in events:
        if is_fun_event(ev):
            span = _span(ev)
            if span is not None:
                funs.append(span)
    cursor = max(wake_edge(events, now, day_start), spans[0][1])
    holes: list[dict] = []
    for start, end in spans[1:]:
        gap = (start - cursor).total_seconds() / 60.0
        if gap >= min_gap and not _covered(funs, cursor, start):
            holes.append({"start": cursor, "end": start, "minutes": gap})
        cursor = max(cursor, end)
    if bound is None or not _did_tasks(events, day_start):
        return holes
    # Хвост дня: сон наступил — промежуток до его начала последняя дыра.
    # Если сам «СОН» синий, его начало уже правый край дыры выше, а курсор
    # ушёл за сон, поэтому двойного списания не выходит.
    gap = (bound - cursor).total_seconds() / 60.0
    if gap >= min_gap and not _covered(funs, cursor, bound):
        holes.append({"start": cursor, "end": bound, "minutes": gap})
    return holes
