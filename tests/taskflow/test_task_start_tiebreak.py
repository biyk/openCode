# TOOLTIP: Тесты тай-брейка EventMatch: равные по похожести — берём раннее по времени
"""Правило выбора при равной похожести заголовков (lib.task_start._search).

Если нескольким мероприятиям фраза подходит ОДИНАКОВО хорошо, берём то, что
раньше по времени начала. Раньше ничью решал самый длинный заголовок, из-за чего
«почистил зубы» утром уходило в «…вечер. Расстелить кровать» (длиннее). Время —
вторичный признак ПОСЛЕ похожести: более точное, но позднее событие по-прежнему
сильнее раннего слабого.
"""

from datetime import datetime, timedelta, timezone

from lib.task_start import TaskStartHandler

TZ = timezone(timedelta(hours=3))
DAY = datetime(2026, 9, 25, tzinfo=TZ)
DESC = "ссылка https://x/#/t uuid 6a1c2d3e-4f50-5152-a3a4-b5c6d7e8f901"


def _ev(title, hour):
    """Событие с заданным часом начала (нужно только для порядка по времени)."""
    start = DAY.replace(hour=hour, minute=0)
    return {"id": title, "summary": title, "description": DESC,
            "start": start.isoformat(),
            "end": (start + timedelta(hours=1)).isoformat()}


def _handler(events):
    """Хендер с календарём-заглушкой; таблицу не трогаем (use_sheet=False)."""
    class _Cal:
        def list_events_between(self, _a, _b):
            return events
    return TaskStartHandler(gcal=_Cal(), sheet=object(),
                            now=DAY.replace(hour=12))


def test_equal_score_prefers_earliest_event():
    """Оба «зубы» = 0.8: берём утреннее, хотя вечернее длиннее и первым в списке."""
    h = _handler([_ev("Почистить зубы вечер. Расстелить кровать", 21),
                  _ev("Почистить зубы утро", 8)])
    ev = h.find_task_event("я почистил зубы", use_sheet=False)
    assert ev is not None and ev["summary"] == "Почистить зубы утро"


def test_earliest_wins_regardless_of_list_order():
    """Порядок в списке не важен: сортировка по времени делает выбор устойчивым."""
    utro = _ev("Почистить зубы утро", 8)
    vecher = _ev("Почистить зубы вечер", 21)
    a = _handler([utro, vecher]).find_task_event(
        "я почистил зубы", use_sheet=False)
    b = _handler([vecher, utro]).find_task_event(
        "я почистил зубы", use_sheet=False)
    assert a["summary"] == "Почистить зубы утро"
    assert b["summary"] == a["summary"]


def test_higher_score_beats_earlier_time():
    """Время — только тай-брейк: более похожее, но позднее событие сильнее."""
    h = _handler([_ev("Полить цветы", 6), _ev("Почистить зубы", 21)])
    ev = h.find_task_event("я почистил зубы", use_sheet=False)
    assert ev is not None and ev["summary"] == "Почистить зубы"


def test_sheet_events_without_start_keep_first():
    """У псевдо-событий таблицы старта нет — при равной похожести берём первую строку."""
    a = _ev("Почистить зубы раз", 8) | {"start": None, "end": None}
    b = _ev("Почистить зубы два", 21) | {"start": None, "end": None}
    ev = _handler([a, b]).find_task_event("я почистил зубы", use_sheet=False)
    assert ev is not None and ev["summary"] == "Почистить зубы раз"
