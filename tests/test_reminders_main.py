"""Тесты напоминаний: CLI main."""


from datetime import datetime
from lib.reminders import main
from lib.time_parser import ReminderSpec


class TestRemindersMain:
    """Команда create, авторизация, ошибки API."""

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
