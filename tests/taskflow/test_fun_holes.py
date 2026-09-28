"""Тесты поиска дыр между синими задачами (lib/taskflow/fun_holes)."""

from datetime import datetime

from lib.core.tuning import FUN_FALLBACK_COLOR
from lib.taskflow.fun_holes import (FUN_MARKER, find_holes, fun_color,
                                    is_fun_event)

TZ = datetime.now().astimezone().tzinfo
NOW = datetime(2026, 9, 28, 14, 0, tzinfo=TZ)
WAKE = (6, 0)


def _dt(pair):
    return datetime(2026, 9, 28, pair[0], pair[1], tzinfo=TZ)


def _ev(start, end, color="", summary="Задача", desc=""):
    """Событие вида list_events_between: время — ISO-строки с часовым поясом."""
    return {"id": f"{summary}-{start}", "summary": summary,
            "start": _dt(start).isoformat(), "end": _dt(end).isoformat(),
            "description": desc, "colorId": color}


def _sleep(end=(9, 0)):
    """«СОН» (тоже colorId=7) до момента пробуждения."""
    return _ev(WAKE, end, color="7", summary="СОН")


def _holes(events, min_gap=1.0):
    return [(h["start"], h["end"], round(h["minutes"]))
            for h in find_holes(events, NOW, min_gap)]


class TestHolesBetweenBlueEvents:
    """Дыра — промежуток между соседними colorId=7, прочие цвета не мешают."""

    def test_hole_spans_other_colored_events(self):
        """Между синими стоит чужое событие — дыра всё равно находится."""
        events = [_sleep(), _ev((9, 0), (9, 30), color="7"),
                  _ev((9, 40), (9, 50), color="2", summary="Игры на компе"),
                  _ev((10, 0), (10, 30), color="7")]
        assert _holes(events) == [(_dt((9, 30)), _dt((10, 0)), 30)]

    def test_hole_right_after_wake_is_a_hole(self):
        """Промежуток от пробуждения до первой синей задачи — тоже дыра."""
        events = [_sleep((9, 0)), _ev((10, 0), (10, 30), color="7"),
                  _ev((11, 0), (11, 30), color="7")]
        assert [h[2] for h in _holes(events)] == [60, 30]

    def test_nothing_after_last_blue_event(self):
        """После последней синей задачи дыры нет: правого края нет."""
        events = [_sleep(), _ev((9, 0), (9, 30), color="7")]
        assert _holes(events) == []

    def test_overlapping_blues_do_not_produce_negative_gap(self):
        """Галочки ставятся задним числом и перекрываются — дыры не возникает."""
        events = [_sleep(), _ev((9, 0), (9, 30), color="7"),
                  _ev((9, 20), (9, 40), color="7"),
                  _ev((9, 35), (9, 50), color="7")]
        assert _holes(events) == []

    def test_gap_shorter_than_min_is_ignored(self):
        """min_gap отсекает короткие щели, длинные остаются."""
        events = [_sleep(), _ev((9, 0), (9, 30), color="7"),
                  _ev((9, 40), (9, 45), color="7"),
                  _ev((10, 30), (11, 0), color="7")]
        assert [h[2] for h in _holes(events, min_gap=15)] == [45]

    def test_filled_hole_is_not_repeated(self):
        """Маркер в description: дыра закрыта — второй раз не тратим деньги."""
        events = [_sleep(), _ev((9, 0), (9, 30), color="7"),
                  _ev((9, 30), (10, 0), color="5", summary="1час развлечений",
                      desc=FUN_MARKER),
                  _ev((10, 0), (10, 30), color="7")]
        assert _holes(events) == []
        assert is_fun_event(events[2])

    def test_holes_inside_sleep_are_out_of_window(self):
        """Окно начинается пробуждением: сон и всё внутри сна не трогаем."""
        events = [_sleep((8, 0)), _ev((6, 30), (6, 45), color="7"),
                  _ev((7, 30), (7, 45), color="7"),
                  _ev((9, 0), (9, 30), color="7"),
                  _ev((10, 0), (10, 30), color="7")]
        holes = _holes(events)
        assert [h[2] for h in holes] == [60, 30]
        assert holes[0][0] == _dt((8, 0))


class TestFunColor:
    """Цвет развлечений берётся у мероприятия-донора («тест для цвета»)."""

    def test_color_taken_from_donor_event(self):
        events = [_ev((0, 30), (0, 45), color="9", summary="тест для цвета")]
        assert fun_color(events) == "9"

    def test_donor_search_ignores_case_and_spaces(self):
        events = [_ev((0, 30), (0, 45), color="3", summary=" Тест Для Цвета ")]
        assert fun_color(events) == "3"

    def test_latest_donor_wins(self):
        events = [_ev((0, 30), (0, 45), color="3", summary="тест для цвета"),
                  _ev((1, 30), (1, 45), color="9", summary="тест для цвета")]
        assert fun_color(events) == "9"

    def test_missing_donor_falls_back(self):
        events = [_ev((0, 30), (0, 45), color="3", summary="Зарядка")]
        assert fun_color(events) == FUN_FALLBACK_COLOR
