"""Тесты напоминаний: разбор фраз, создание."""


from datetime import datetime
from lib.reminders import ReminderHandler, _clean_candidate
from lib.scheduling.time_parser import ReminderSpec, TimeParser


class TestCleanCandidate:
    """Удаление триггеров и заполнителей."""

    def test_basic(self):
        """«напомни позвонить маме» → «позвонить маме»."""
        assert _clean_candidate("напомни позвонить маме") == "позвонить маме"

    def test_with_me(self):
        """«напомни мне купить молоко» → «купить молоко»."""
        assert _clean_candidate("напомни мне купить молоко") == "купить молоко"

    def test_me_plus_pozhaluista(self):
        """«напомни мне пожалуйста через десять часов...» → «через ...»."""
        assert _clean_candidate(
            "напомни мне пожалуйста через десять часов захватить мир") == \
            "через десять часов захватить мир"

    def test_multiple_fillers(self):
        """Несколько заполнителей подряд убираются все."""
        assert _clean_candidate(
            "напомни пожалуйста алиса через час убраться") == "через час убраться"

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
    """Распознавание команды напоминания."""

    def _handler(self):
        mock_google = type("G", (), {"create_reminder": lambda **kw: "e"})()
        return ReminderHandler(google=mock_google)

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
    """Извлечение времени и текста."""

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

    def test_no_time_defaults_plus_60(self):
        """Фраза без времени → через 60 минут от текущего момента."""
        now = datetime(2026, 9, 15, 10, 0)
        h = self._handler(now=now)
        spec = h.create("напомни купить капусту")
        assert spec is not None
        assert spec.when == datetime(2026, 9, 15, 11, 0)
        assert spec.text == "купить капусту"

    def test_empty_phrase_returns_none(self):
        """Пустая фраза после очистки → None."""
        h = self._handler()
        assert h.create("напомни") is None


class TestAddEvent:
    """Создание события в календаре."""

    def test_success(self):
        """Успешное создание напоминания → event_id."""
        mock_google = type("G", (), {
            "create_reminder": lambda self, **kw: "event123",
        })()
        handler = ReminderHandler(google=mock_google)
        spec = ReminderSpec(
            when=datetime(2026, 9, 15, 13, 0), text="постирать")
        assert handler.add_event(spec) == "event123"

    def test_failure_returns_none(self):
        """Ошибка Google API → None."""
        mock_google = type("G", (), {
            "create_reminder": lambda self, **kw: (_ for _ in ()).throw(
                Exception("no creds")),
        })()
        handler = ReminderHandler(google=mock_google)
        spec = ReminderSpec(
            when=datetime(2026, 9, 15, 13, 0), text="тест")
        assert handler.add_event(spec) is None


class TestIntegration:
    """Сквозной сценарий напоминания."""

    def test_full_flow(self):
        """Полный сценарий: текст → событие создано."""
        now = datetime(2026, 9, 15, 10, 0)
        created = {}

        def fake_create(self, **kw):
            created.update(kw)
            return "event_ok"

        mock_google = type("G", (), {"create_reminder": fake_create})()
        tp = TimeParser(now=now)
        handler = ReminderHandler(google=mock_google, parser=tp)
        spec = handler.create(
            "напомни мне через 30 минут позвонить маме")
        assert spec is not None
        assert spec.when.hour == 10 and spec.when.minute == 30
        assert spec.text == "позвонить маме"
        eid = handler.add_event(spec)
        assert eid == "event_ok"
        assert created["summary"] == "позвонить маме"

    def test_full_flow_no_time(self):
        """Без времени — событие на now+60, текст — вся фраза."""
        now = datetime(2026, 9, 15, 10, 0)
        tp = TimeParser(now=now)
        handler = ReminderHandler(parser=tp)
        spec = handler.create("напомни помыть полы")
        assert spec is not None
        assert spec.when == datetime(2026, 9, 15, 11, 0)
        assert spec.text == "помыть полы"
