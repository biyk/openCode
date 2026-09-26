"""Тесты Google Calendar: OAuth-авторизация."""


import pytest
from google.oauth2.credentials import Credentials
from lib.google_calendar import GoogleCalendar, GoogleOAuthError


class FakeCalendarResource:
    """Фейк events-ресурса (insert + list)."""

    def __init__(self, log, event_items=None):
        self._log = log
        self._event_items = event_items or []

    def events(self):
        return self

    def insert(self, calendarId=None, body=None):
        self._log.append(("event", calendarId, body))
        return FakeRequest({"id": "event-1"})

    def list(self, **kw):
        return FakeRequest({"items": self._event_items})


class FakeService:
    """Заглушка googleapiclient discovery.build."""

    def __init__(self, event_items=None):
        self.log = []
        self._calendar = FakeCalendarResource(self.log, event_items=event_items)

    def events(self):
        return self._calendar

    @property
    def created(self):
        return [b for kind, _, b in self.log if kind == "event"]


class FakeRequest:
    """Результат execute() запроса."""

    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class TestAuthorize:
    """OAuth-флоу, scope, готовность."""

    @staticmethod
    def _write_token(path, scopes):
        """Пишет валидный (не протухший) token.json с заданным scope."""
        import json
        path.write_text(json.dumps({
            "token": "access_token",
            "refresh_token": "refresh_token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "c",
            "client_secret": "s",
            "scopes": scopes,
            "expiry": "2099-01-01T00:00:00Z",
        }), encoding="utf-8")

    def test_authorize_builds_services(self, tmp_path):
        """Успешная авторизация создаёт сервисы."""
        g = GoogleCalendar(
            token_file=str(tmp_path / "token.json"),
            credentials_file=str(tmp_path / "creds.json"))
        fake_creds = Credentials.from_authorized_user_info(
            {"token": "t", "refresh_token": "r",
             "client_id": "c", "client_secret": "s"})
        g._load_or_get_credentials = lambda: fake_creds
        g._build_services = lambda c: None
        g.authorize()
        assert g.is_ready() is False

    def test_missing_credentials_file(self, tmp_path):
        """Нет credentials.json → GoogleOAuthError."""
        g = GoogleCalendar(
            credentials_file=str(tmp_path / "missing.json"),
            token_file=str(tmp_path / "token.json"))
        with pytest.raises(Exception):
            g._load_or_get_credentials()

    def test_is_ready_false_when_calendar_scope_missing(self, tmp_path):
        """Валидный tokens-only токен НЕ готов для календаря."""
        tok = tmp_path / "token.json"
        self._write_token(tok, ["https://www.googleapis.com/auth/tasks"])
        g = GoogleCalendar(
            token_file=str(tok),
            credentials_file=str(tmp_path / "creds.json"))
        assert g.is_ready() is False

    def test_is_ready_true_when_all_scopes_present(self, tmp_path):
        """Токен со всеми скоупами (calendar, tasks, sheets) готов."""
        tok = tmp_path / "token.json"
        self._write_token(tok, [
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/tasks",
            "https://www.googleapis.com/auth/spreadsheets",
        ])
        g = GoogleCalendar(
            token_file=str(tok),
            credentials_file=str(tmp_path / "creds.json"))
        assert g.is_ready() is True

    def test_missing_scope_triggers_reauth(self, tmp_path):
        """Нехватка scope → не возвращаем валидный токен, а идём в flow."""
        tok = tmp_path / "token.json"
        self._write_token(tok, ["https://www.googleapis.com/auth/tasks"])
        g = GoogleCalendar(
            token_file=str(tok),
            credentials_file=str(tmp_path / "missing.json"))
        with pytest.raises(GoogleOAuthError):
            g._load_or_get_credentials()
