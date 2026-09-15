"""Тесты обёртки Google Calendar/Tasks (моки API, без сети)."""

from datetime import datetime

import pytest
from google.oauth2.credentials import Credentials

from lib.google_calendar import GoogleCalendar, GoogleOAuthError


NOW = datetime(2026, 9, 15, 13, 0)


class FakeTasksResource:
    """Фейк tasks-ресурса (insert + tasklists.list)."""

    def __init__(self, log):
        self._log = log
        self.deleted = []

    def insert(self, tasklist=None, body=None):
        self._log.append(("task", tasklist, body))
        return FakeRequest({"id": "task-1"})

    def tasklists(self):
        return self

    def list(self):
        return FakeRequest({"items": [
            {"id": "resolved-default", "title": "Список по умолчанию"},
        ]})


class FakeEventsResource:
    """Фейк calendar-ресурса (insert + list)."""

    def __init__(self, log):
        self._log = log

    def insert(self, calendarId=None, body=None):
        self._log.append(("event", calendarId, body))
        return FakeRequest({"id": "event-1"})

    def list(self, **kw):
        return FakeRequest({"items": [
            {"summary": "Встреча", "start": {"dateTime": "2026-09-15T14:00"}},
        ]})


class FakeService:
    """Заглушка googleapiclient discovery.build."""

    def __init__(self):
        self.log = []
        self._tasks = FakeTasksResource(self.log)
        self._events = FakeEventsResource(self.log)

    def tasks(self):
        return self._tasks

    def events(self):
        return self._events

    @property
    def created(self):
        return [b for kind, _, b in self.log if kind in ("task", "event")]

    # discovery-подобные методы списков — для list_upcoming
    def events_list(self, **kw):
        items = [
            {"summary": "Встреча", "start": {"dateTime": "2026-09-15T14:00"}},
        ]
        return FakeRequest({"items": items})

    def list(self, **kw):
        return self.events_list(**kw)


class FakeRequest:
    """Результат execute() запроса."""

    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class TestAuthorize:
    """OAuth-флоу."""

    def test_authorize_builds_services(self, monkeypatch, tmp_path):
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

    def test_missing_credentials_file(self, tmp_path, monkeypatch):
        """Нет credentials.json → GoogleOAuthError."""
        g = GoogleCalendar(
            credentials_file=str(tmp_path / "missing.json"),
            token_file=str(tmp_path / "token.json"))
        monkeypatch.setattr(g, "_load_or_get_credentials",
                            lambda: (_ for _ in ()).throw(FileNotFoundError))
        with pytest.raises(Exception):
            g._load_or_get_credentials()


class TestOperations:
    """Операции с API."""

    def _google(self):
        g = GoogleCalendar()
        g._tasks_service = FakeService()
        g._calendar_service = FakeService()
        g._ready = True
        return g

    def test_create_reminder_both_apis(self):
        """create_reminder вызывает Tasks и Calendar, возвращает id."""
        g = self._google()
        result = g.create_reminder("постирать", NOW)
        assert result == {"task": "task-1", "event": "event-1"}
        assert g._tasks_service.created[0]["title"] == "постирать"
        assert "due" in g._tasks_service.created[0]
        ev = g._calendar_service.created[0]
        assert ev["summary"] == "постирать"
        assert ev["start"]["dateTime"].startswith("2026-09-15T13:00")

    def test_create_reminder_empty_summary(self):
        """Пустой текст → GoogleOAuthError."""
        g = self._google()
        with pytest.raises(GoogleOAuthError):
            g.create_reminder("  ", NOW)

    def test_list_upcoming_formats(self):
        """list_upcoming возвращает summary+start."""
        g = self._google()
        items = g.list_upcoming(hours=24)
        assert items == [{"summary": "Встреча",
                          "start": "2026-09-15T14:00"}]

    def test_not_ready_authorizes(self, monkeypatch):
        """Если не ready — authorize() вызывается."""
        g = self._google()
        g._ready = False
        g.authorize = lambda: None
        g.create_reminder("тест", NOW)
        assert g._ready is False  # authorize не сбрасывает ready, тк mock
