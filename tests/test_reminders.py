"""Тесты обработчика напоминаний (ReminderHandler)."""

from datetime import datetime

from lib.reminders import ReminderHandler, _clean_candidate, main
from lib.time_parser import ReminderSpec, TimeParser


class TestCleanCandidate:
    """Удаление триггеров и заполнителей из фразы."""

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
    """Определение, является ли текст напоминанием."""

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
    """Вызов Google Calendar API (mock)."""

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
    """Интеграция полного цикла: текст → spec → mock calendar."""

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


class TestRemindersMain:
    """CLI `python -m lib.reminders` для команды calendar-reminder."""

    def _patch_handler(self, fake):
        import lib.reminders as rem_module
        real = rem_module.ReminderHandler
        rem_module.ReminderHandler = lambda *a, **k: fake
        return real

    def _fake(self, spec=None, auth=True, event_id="event-1"):
        from lib.google_calendar import GoogleOAuthError

        class Fake:
            def create(self, phrase):
                return spec

            def authorize(self):
                if not auth:
                    raise GoogleOAuthError("нет consent")

            def auth_ready(self):
                return auth

            def add_event(self, passed):
                assert passed is spec
                return event_id
        return Fake()

    def test_main_creates_event(self, capsys):
        """Фраза с временем — событие создано, код 0, озвучка «Готово»."""
        import lib.reminders as rem_module
        spec = ReminderSpec(
            when=datetime(2026, 9, 15, 11, 0), text="позвонить маме")
        real = self._patch_handler(self._fake(spec=spec))
        voiced = []
        fake_tts = type("T", (), {
            "speak_and_play": lambda self, text: voiced.append(text),
        })()
        real_tts = rem_module.TextToSpeech
        rem_module.TextToSpeech = lambda *a, **k: fake_tts
        try:
            code = main(["через час позвонить маме"])
        finally:
            rem_module.ReminderHandler = real
            rem_module.TextToSpeech = real_tts
        out = capsys.readouterr().out
        assert code == 0
        assert "reminder: позвонить маме" in out
        assert "event_id: event-1" in out
        assert voiced == ["Готово"]

    def test_main_no_args_usage(self, capsys):
        """Без фразы — usage, код 2."""
        assert main([]) == 2
        assert "usage" in capsys.readouterr().out

    def test_main_empty_phrase(self, capsys):
        """Пустая фраза — код 3."""
        import lib.reminders as rem_module
        real = self._patch_handler(self._fake(spec=None))
        try:
            code = main(["   "])
        finally:
            rem_module.ReminderHandler = real
        assert code == 3

    def test_main_no_auth(self, capsys):
        """Нет авторизации Calendar — код 3."""
        import lib.reminders as rem_module
        spec = ReminderSpec(
            when=datetime(2026, 9, 15, 11, 0), text="позвонить маме")
        real = self._patch_handler(self._fake(spec=spec, auth=False))
        try:
            code = main(["через час позвонить маме"])
        finally:
            rem_module.ReminderHandler = real
        out = capsys.readouterr().out
        assert code == 3
        assert "авторизации" in out

    def test_main_api_failure(self, capsys):
        """API вернуло None — код 1."""
        import lib.reminders as rem_module
        spec = ReminderSpec(
            when=datetime(2026, 9, 15, 11, 0), text="позвонить маме")
        real = self._patch_handler(
            self._fake(spec=spec, event_id=None))
        try:
            code = main(["через час позвонить маме"])
        finally:
            rem_module.ReminderHandler = real
        assert code == 1
