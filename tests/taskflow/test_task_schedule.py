"""тесты lib/taskflow/task_schedule.py — время-зависимый выбор задач.

Сеть не трогаем: события/строки/now инжектятся. Проверяем «идущая сейчас или
следующая», три кнопки от now до «СОН», отсечку запущенных/галочек и откат к
таблице без событий.
"""

from datetime import datetime, timedelta

from lib.taskflow.task_schedule import (current_or_next, idle_offer,
                                        sleep_edge, upcoming_titles)

BASE = datetime.now().astimezone()
UA = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
UB = "11111111-2222-3333-4444-555555555555"
UC = "99999999-8888-7777-6666-555555555555"
UD = "deadbeef-1111-2222-3333-444444444444"


def _rel(minutes):
    return BASE + timedelta(minutes=minutes)


def _event(uuid, start_min, end_min, summary="Задача", color=""):
    return {"id": uuid, "summary": summary, "colorId": color,
            "description": uuid,
            "start": _rel(start_min).isoformat(),
            "end": _rel(end_min).isoformat()}


def _row(title, uuid, start_date=0):
    return {"task_title": title, "task_uuid": uuid, "start_date": start_date,
            "task_time": 30}


ROWS = [_row("А", UA), _row("Б", UB), _row("В", UC), _row("Г", UD)]


class TestCurrentOrNext:
    def test_running_now_wins_over_later(self):
        events = [_event(UA, -30, 30), _event(UB, 60, 90)]
        assert current_or_next(ROWS, events, BASE) == "А"

    def test_nothing_running_takes_next(self):
        events = [_event(UB, 60, 90), _event(UC, 120, 150)]
        assert current_or_next(ROWS, events, BASE) == "Б"

    def test_all_finished_is_none(self):
        events = [_event(UA, -90, -60)]
        assert current_or_next(ROWS, events, BASE) is None

    def test_started_task_not_offered(self):
        rows = [_row("А", UA, start_date=1)]
        events = [_event(UA, -30, 30)]
        assert current_or_next(rows, events, BASE) is None


class TestUpcomingTitles:
    def test_three_soonest_only(self):
        events = [_event(UA, 10, 20), _event(UB, 60, 70),
                  _event(UC, 120, 130), _event(UD, 180, 190)]
        assert upcoming_titles(ROWS, events, BASE, until=None,
                               limit=3) == ["А", "Б", "В"]

    def test_cut_at_sleep_edge(self):
        events = [_event(UA, 10, 20), _event(UB, 60, 70),
                  _event(UC, 120, 130), _event(UD, 200, 210),
                  _event("s", 180, 600, summary="СОН")]
        titles = upcoming_titles(ROWS, events, BASE, until=_rel(180),
                                 limit=3)
        assert titles == ["А", "Б", "В"]

    def test_done_marker_event_skipped(self):
        events = [_event(UA, 10, 20, color="7")]
        assert upcoming_titles(ROWS, events, BASE) == []


class TestSleepEdge:
    def test_next_sleep_only(self):
        events = [_event("w", -600, -30, summary="СОН"),   # прошлый (пробуждение)
                  _event("s", 180, 480, summary="СОН")]    # сегодня вечером
        assert sleep_edge(events, BASE) == _rel(180)

    def test_no_sleep_returns_none(self):
        assert sleep_edge([_event(UA, 10, 20)], BASE) is None


class TestIdleOffer:
    def test_fallback_without_events(self):
        voice, titles = idle_offer(ROWS, None, BASE)
        assert voice == "А"                    # первая незапущенная строки
        assert titles == []

    def test_voice_and_buttons_with_events(self):
        events = [_event(UA, -5, 25), _event(UB, 40, 50), _event(UC, 90, 100),
                  _event(UD, 300, 320), _event("s", 180, 400, summary="СОН")]
        voice, titles = idle_offer(ROWS, events, BASE)
        assert voice == "А"                    # идёт сейчас
        assert titles == ["А", "Б", "В"]       # до сна, три
