"""Тесты поиска дыр между синими задачами (lib/taskflow/fun_holes)."""

from datetime import datetime, timedelta

from lib.core.tuning import FUN_FALLBACK_COLOR
from lib.taskflow.fun_holes import (FUN_MARKER, find_holes, fun_color,
                                    is_fun_event, sleep_start)

TZ = datetime.now().astimezone().tzinfo
NOW = datetime(2026, 9, 28, 14, 0, tzinfo=TZ)
WAKE = (6, 0)


def _dt(pair):
    return datetime(2026, 9, 28, pair[0], pair[1], tzinfo=TZ)


def _ev(start, end, color="", summary="Задача", desc=""):
    """Событие вида list_events_between: время — ISO-строки с часовым поясом.

    Конец раньше начала (сон 23:00 → 07:00) уводит конец на сутки вперёд:
    `_span` такой перевёрнутый интервал иначе отбрасывает как пустой.
    """
    s, e = _dt(start), _dt(end)
    if e <= s:
        e += timedelta(days=1)
    return {"id": f"{summary}-{start}", "summary": summary,
            "start": s.isoformat(), "end": e.isoformat(),
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


def _day():
    """Подъём в 09:00, синие задачи 09:00–09:30 и 10:00–10:30."""
    return [_ev((6, 0), (9, 0), color="7", summary="СОН"),
            _ev((9, 0), (9, 30), color="7"),
            _ev((10, 0), (10, 30), color="7")]


def _sleep_running(color="1"):
    """«СОН» на 23:00 сегодня, конец завтра в 07:00 — идёт прямо сейчас."""
    return _ev((23, 0), (7, 0), color=color, summary="СОН")


LATE = datetime(2026, 9, 28, 23, 20, tzinfo=TZ)


class TestSleepClosesTheDay:
    """Начало сна — последняя граница, где ещё считаем дыры (§4.4)."""

    def _late(self, events, now=LATE, min_gap=1.0):
        return [(h["start"], h["end"], round(h["minutes"]))
                for h in find_holes(events, now, min_gap)]

    def test_tail_to_sleep_start_is_a_hole(self):
        """Сон наступил, он не синий: хвост дня закрывается как дыра."""
        assert self._late(_day() + [_sleep_running()]) == [
            (_dt((9, 30)), _dt((10, 0)), 30),
            (_dt((10, 30)), _dt((23, 0)), 750)]

    def test_tail_not_counted_while_sleep_is_ahead(self):
        """Сон ещё в будущем: хвост не трогаем — туда пишет автоплан."""
        assert self._late(_day() + [_sleep_running()], now=NOW) == [
            (_dt((9, 30)), _dt((10, 0)), 30)]

    def test_blue_sleep_yields_one_tail(self):
        """«СОН» colorId=7: хвост даёт одну дыру, а не две."""
        holes = self._late(_day() + [_sleep_running(color="7")])
        assert [h[2] for h in holes] == [30, 750]
        assert sum(1 for h in holes if h[1] == _dt((23, 0))) == 1

    def test_running_sleep_keeps_the_wake_edge(self):
        """Конец идущего сна (завтра) не становится левым краем окна."""
        assert self._late(_day() + [_sleep_running()])[0][0] == _dt((9, 30))

    def test_task_running_into_sleep_is_not_negative(self):
        """Задача залезла в сон: дыра до неё, отрицательного хвоста нет."""
        events = [_ev((9, 0), (9, 30), color="7"),
                  _ev((22, 0), (23, 30), color="7"), _sleep_running()]
        assert [h[2] for h in self._late(events)] == [750]

    def test_filled_tail_is_not_repeated(self):
        """Хвост закрыт нашим «Отдыхом» — деньги повторно не списываются."""
        closed = _ev((10, 30), (23, 0), color="5", summary="Отдых",
                     desc=FUN_MARKER)
        assert self._late(_day() + [closed, _sleep_running()]) == [
            (_dt((9, 30)), _dt((10, 0)), 30)]

    def test_day_without_tasks_has_no_tail(self):
        """Ни одной выполненной задачи: дыра «весь день» не списывается."""
        events = [_ev((6, 0), (9, 0), color="7", summary="СОН"),
                  _sleep_running()]
        assert self._late(events) == []

    def test_sleep_start_ignores_finished_and_future(self):
        """Граница — только у идущего сна: будущий и завершившийся не годятся."""
        running = _sleep_running()
        assert sleep_start([running], LATE) == _dt((23, 0))
        assert sleep_start([running], NOW) is None
        ended = _ev((6, 0), (9, 0), color="1", summary="СОН")
        assert sleep_start([ended], LATE) is None
