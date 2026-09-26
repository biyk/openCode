"""Тесты обработчика запросов планов (PlansHandler)."""

from datetime import datetime, timedelta

from lib.plans import PlansHandler, TRIGGER_PHRASES


NOW = datetime(2026, 9, 15, 13, 0)


class TestIsPlansQuery:
    """Определение, является ли текст запросом планов."""

    def _handler(self):
        return PlansHandler(google=object())

    def test_positive(self):
        """Прямая фраза распознаётся."""
        assert self._handler().is_plans_query("что у меня сейчас по планам")

    def test_positive_with_trigger(self):
        """С триггером «алиса» фраза тоже распознаётся."""
        assert self._handler().is_plans_query(
            "алиса что у меня сейчас по планам")
        assert self._handler().is_plans_query(
            "что у меня сейчас по планам пожалуйста")

    def test_positive_variants(self):
        """Разные формулировки распознаются."""
        for p in TRIGGER_PHRASES:
            assert self._handler().is_plans_query(p)

    def test_negative(self):
        """Обычная команда — не запрос планов."""
        assert not self._handler().is_plans_query("включи ютуб")

    def test_case_insensitive_yoyo(self):
        """Ё→е: фраза с ё нормализуется."""
        assert self._handler().is_plans_query("что у меня сейчас по планам")

    def test_schedule_word_recognized(self):
        """«по расписанию» в разных искажениях Vosk — запрос планов."""
        assert self._handler().is_plans_query(
            "что мне сейчас по расписание пожалуйста")
        assert self._handler().is_plans_query("что у меня сейчас по расписанию")
        assert self._handler().is_plans_query("какое у меня расписание")
        assert self._handler().is_plans_query(
            "что у меня сейчас про списанию")
        assert self._handler().is_plans_query(
            "пожалуйста что у меня сейчас про списанию")

    def test_empty(self):
        """Пустой текст — не запрос планов."""
        assert not self._handler().is_plans_query("")


class FakeCalendar:
    """Заглушка GoogleCalendar.pending_events."""

    def __init__(self, events=None):
        self._events = events or []

    def pending_events(self, limit=50):
        return list(self._events)


class TestCurrentTask:
    """Выбор актуальной задачи из календаря."""

    def _handler(self, events, now=None):
        return PlansHandler(google=FakeCalendar(events), now=now or NOW)

    @staticmethod
    def _ev(sid, summary, start, end):
        return {"id": sid, "summary": summary, "start": start, "end": end}

    def test_no_events_returns_none(self):
        h = self._handler([])
        assert h.current_task() is None

    def test_picks_running_event(self):
        """Идущее сейчас событие побеждает будущее."""
        running = self._ev("r", "созвон", NOW - timedelta(minutes=5),
                           NOW + timedelta(minutes=25))
        later = self._ev("l", "ужин", NOW + timedelta(hours=2),
                         NOW + timedelta(hours=3))
        task = self._handler([later, running]).current_task()
        assert task is not None
        assert task["id"] == "r"

    def test_picks_nearest_future(self):
        """Нет текущего — берётся ближайшее будущее."""
        far = self._ev("f", "далёкое", NOW + timedelta(hours=5),
                       NOW + timedelta(hours=6))
        near = self._ev("n", "близкое", NOW + timedelta(minutes=20),
                        NOW + timedelta(minutes=50))
        task = self._handler([far, near]).current_task()
        assert task is not None
        assert task["id"] == "n"

    def test_ignores_finished_events(self):
        """Завершённые события игнорируются (их нет в pending_events)."""
        finished = self._ev("f", "закончилось", NOW - timedelta(hours=2),
                            NOW - timedelta(hours=1))
        task = self._handler([finished]).current_task()
        assert task is None


class TestAuthReady:
    """Проверка готовности авторизации."""

    def test_delegates_to_google(self):
        google = FakeCalendar()
        google.is_ready = lambda: True
        assert PlansHandler(google=google).auth_ready() is True

    def test_google_not_ready(self):
        google = FakeCalendar()
        google.is_ready = lambda: False
        assert PlansHandler(google=google).auth_ready() is False

    def test_default_google_used_when_not_injected(self):
        """Без google — используется реальный GoogleCalendar (мок is_ready)."""
        from lib.google_calendar import GoogleCalendar
        h = PlansHandler.__new__(PlansHandler)
        h._now = NOW
        fake = GoogleCalendar()
        fake.is_ready = lambda: False
        h._google = fake
        assert h.auth_ready() is False
