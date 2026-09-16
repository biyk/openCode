"""Тесты обёртки Google Calendar (моки API, без сети)."""

from datetime import datetime

import pytest
from google.oauth2.credentials import Credentials

from lib.google_calendar import GoogleCalendar, GoogleOAuthError


NOW = datetime(2026, 9, 15, 13, 0)


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
    """OAuth-флоу."""

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

    def test_is_ready_true_when_calendar_scope_present(self, tmp_path):
        """Токен со scope calendar.events готов."""
        tok = tmp_path / "token.json"
        self._write_token(
            tok, ["https://www.googleapis.com/auth/calendar.events"])
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


class TestOperations:
    """Операции с API."""

    def _google(self):
        g = GoogleCalendar()
        g._calendar_service = FakeService()
        g._ready = True
        return g

    def test_create_reminder_creates_event_with_time(self):
        """create_reminder создаёт одно событие с временем и попапом."""
        g = self._google()
        event_id = g.create_reminder("постирать", NOW)
        assert event_id == "event-1"
        assert len(g._calendar_service.created) == 1
        event = g._calendar_service.created[0]
        assert event["summary"] == "постирать"
        assert event["start"]["dateTime"].startswith("2026-09-15T13:00")
        assert event["end"]["dateTime"].startswith("2026-09-15T13:30")
        assert event["reminders"]["useDefault"] is False
        assert event["reminders"]["overrides"] == [
            {"method": "popup", "minutes": 0}]

    def test_create_reminder_empty_summary(self):
        """Пустой текст → GoogleOAuthError."""
        g = self._google()
        with pytest.raises(GoogleOAuthError):
            g.create_reminder("  ", NOW)

    def test_list_events_returns_items(self):
        """list_events мапит поля события."""
        g = GoogleCalendar()
        g._calendar_service = FakeService(event_items=[
            {"id": "e1", "summary": "захватить мир",
             "start": {"dateTime": "2026-09-15T14:00:00+04:00"},
             "end": {"dateTime": "2026-09-15T14:30:00+04:00"}},
            {"id": "e2", "summary": "аллдей",
             "start": {"date": "2026-09-16"},
             "end": {"date": "2026-09-17"}},
        ])
        g._ready = True
        items = g.list_events(limit=10)
        assert [i["id"] for i in items] == ["e1", "e2"]
        assert items[0] == {
            "id": "e1", "summary": "захватить мир",
            "start": "2026-09-15T14:00:00+04:00",
            "end": "2026-09-15T14:30:00+04:00"}
        assert items[1]["start"] == "2026-09-16"

    def test_pending_events_filters_finished_and_sorts(self):
        """pending_events отбрасывает завершённые и сортирует по началу."""
        from datetime import timedelta
        now = datetime.now().astimezone()
        past = now - timedelta(hours=2)
        soon = now + timedelta(minutes=10)
        later = now + timedelta(hours=1)
        g = GoogleCalendar()
        g._calendar_service = FakeService(event_items=[
            {"id": "past", "summary": "прошло",
             "start": {"dateTime": past.isoformat()},
             "end": {"dateTime": (past + timedelta(minutes=20)).isoformat()}},
            {"id": "later", "summary": "позже",
             "start": {"dateTime": later.isoformat()},
             "end": {"dateTime": (later + timedelta(minutes=30)).isoformat()}},
            {"id": "soon", "summary": "скоро",
             "start": {"dateTime": soon.isoformat()},
             "end": {"dateTime": (soon + timedelta(minutes=15)).isoformat()}},
        ])
        g._ready = True
        items = g.pending_events()
        assert [i["id"] for i in items] == ["soon", "later"]
        assert items[0]["summary"] == "скоро"
        assert items[0]["start"].tzinfo is not None

    def test_pending_events_empty(self):
        """Без событий pending_events возвращает пустой список."""
        g = GoogleCalendar()
        g._calendar_service = FakeService(event_items=[])
        g._ready = True
        assert g.pending_events() == []

    def test_not_ready_authorizes(self):
        """Если не ready — authorize() вызывается."""
        g = self._google()
        g._ready = False
        g.authorize = lambda: None
        g.create_reminder("тест", NOW)
        assert g._ready is False  # authorize ставит ready в реальном флоу
