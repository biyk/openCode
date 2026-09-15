"""Тесты обработчика напоминаний (ReminderHandler)."""

from datetime import datetime

from lib.reminders import ReminderHandler, _clean_candidate
from lib.time_parser import ReminderSpec, TimeParser


class TestCleanCandidate:
    """Удаление триггеров и заполнителей из фразы."""

    def test_basic(self):
        """«напомни позвонить маме» → «позвонить маме»."""
        assert _clean_candidate("напомни позвонить маме") == "позвонить маме"

    def test_with_me(self):
        """«напомни мне купить молоко» → «купить молоко»."""
        assert _clean_candidate("напомни мне купить молоко") == "купить молоко"

    def test_sklad(self):
        """«поставь напоминание на завтра» → «на завтра»."""
        assert _clean_candidate("поставь напоминание на завтра") == "на завтра"

    def test_empty_after_clean(self):
        """Только слово «напомни» — пустой кандидат."""
        assert _clean_candidate("напомни") == ""

    def test_alisa_prefix(self):
        """«напомни алиса через час» → «через час»."""
        assert _clean_candidate("напомни алиса через час") == "через час"

    def test_vosk_napomnim_trailing(self):
        """Vosk «напомним …» не оставляет хвост «м …»."""
        assert _clean_candidate(
            "напомним через десять минут убраться") == \
            "через десять минут убраться"

    def test_vosk_napomnim_trailing_pozhaluista(self):
        """«пожалуйста» в конце после триггера удаляется."""
        assert _clean_candidate(
            "напомним через десять минут убраться пожалуйста") == \
            "через десять минут убраться"


class TestIsReminder:
    """Определение, является ли текст напоминанием."""

    def _handler(self):
        return ReminderHandler()

    def test_positive(self):
        """Фраза начинается с «напомни» → True."""
        assert self._handler().is_reminder("напомни позвонить маме")

    def test_negative(self):
        """Обычный текст — не напоминание."""
        assert not self._handler().is_reminder("включи ютуб")

    def test_variants(self):
        """Разные варианты триггеров распознаются."""
        h = self._handler()
        for p in ["напомни", "поставь напоминание", "создай напоминание"]:
            assert h.is_reminder(f"{p} позвонить")


class TestCreate:
    """Создание напоминания из текста."""

    def _handler(self, now: datetime | None = None):
        tp = TimeParser(now=now or datetime(2026, 9, 15, 10, 0))
        return ReminderHandler(parser=tp)

    def test_basic(self):
        """«напомни через 3 часа постирать белье» → spec with correct time."""
        h = self._handler()
        spec = h.create("напомни через 3 часа постирать белье")
        assert spec is not None
        assert spec.when.hour == 13
        assert spec.text == "постирать белье"

    def test_no_time_returns_none(self):
        """Фраза без времени → None."""
        h = self._handler()
        assert h.create("напомни постирать белье") is None


class TestAddToCalendar:
    """Вызов Google Calendar API (mock)."""

    def test_success(self):
        """Успешное создание напоминания → event_id."""
        mock_google = type("G", (), {
            "create_reminder": lambda self, **kw: {"event": "evt123"},
        })()
        handler = ReminderHandler(google=mock_google)
        spec = ReminderSpec(
            when=datetime(2026, 9, 15, 13, 0), text="постирать")
        assert handler.add_to_calendar(spec) == "evt123"

    def test_failure_returns_none(self):
        """Ошибка Google API → None."""
        mock_google = type("G", (), {
            "create_reminder": lambda self, **kw: (_ for _ in ()).throw(
                Exception("no creds")),
        })()
        handler = ReminderHandler(google=mock_google)
        spec = ReminderSpec(
            when=datetime(2026, 9, 15, 13, 0), text="тест")
        assert handler.add_to_calendar(spec) is None


class TestIntegration:
    """Интеграция полного цикла: текст → spec → mock calendar."""

    def test_full_flow(self):
        """Полный сценарий: текст → напоминание создано."""
        now = datetime(2026, 9, 15, 10, 0)
        created = {}

        def fake_create(self, **kw):
            created.update(kw)
            return {"event": "evt_ok"}

        mock_google = type("G", (), {"create_reminder": fake_create})()
        tp = TimeParser(now=now)
        handler = ReminderHandler(google=mock_google, parser=tp)
        spec = handler.create(
            "напомни мне через 30 минут позвонить маме")
        assert spec is not None
        assert spec.when.hour == 10 and spec.when.minute == 30
        assert spec.text == "позвонить маме"
        eid = handler.add_to_calendar(spec)
        assert eid == "evt_ok"
        assert created["summary"] == "позвонить маме"
