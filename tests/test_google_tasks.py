"""Тесты обёртки Google Tasks (моки API, без сети)."""

import json

import pytest
from google.oauth2.credentials import Credentials

from lib.google_tasks import GoogleTasks, GoogleOAuthError


class FakeTasksResource:
    """Фейк tasks-ресурса (insert/list/patch)."""

    def __init__(self, log):
        self._log = log
        self._tasks = []

    def insert(self, tasklist=None, body=None):
        self._log.append(("insert", tasklist, body))
        task = {"id": "task-1", "title": body.get("title", ""),
                "status": "needsAction"}
        self._tasks.append(task)
        return FakeRequest(task)

    def list(self, tasklist=None, showCompleted=False, **kw):
        self._log.append(("list", tasklist, showCompleted))
        items = [t for t in self._tasks
                 if showCompleted or t.get("status") != "completed"]
        return FakeRequest({"items": items})

    def patch(self, tasklist=None, task=None, body=None):
        self._log.append(("patch", tasklist, task, body))
        for t in self._tasks:
            if t["id"] == task:
                t.update(body or {})
                return FakeRequest(dict(t))
        raise KeyError(f"Задача {task} не найдена")


class FakeService:
    """Заглушка googleapiclient discovery.build для tasks v1."""

    def __init__(self):
        self.log = []
        self._tasks = FakeTasksResource(self.log)

    def tasks(self):
        return self._tasks

    @property
    def created(self):
        return [b for kind, _, b in self.log if kind == "insert"]


class FakeRequest:
    """Результат execute() запроса."""

    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


def _write_token(path, scopes):
    """Пишет валидный (не протухший) token.json с заданным scope."""
    path.write_text(json.dumps({
        "token": "access_token",
        "refresh_token": "refresh_token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "c",
        "client_secret": "s",
        "scopes": scopes,
        "expiry": "2099-01-01T00:00:00Z",
    }), encoding="utf-8")


class TestAuthorize:
    """OAuth-флоу."""

    def test_authorize_builds_services(self, tmp_path):
        """Успешная авторизация помечает сервис готовым."""
        g = GoogleTasks(
            token_file=str(tmp_path / "token.json"),
            credentials_file=str(tmp_path / "creds.json"))
        fake_creds = Credentials.from_authorized_user_info(
            {"token": "t", "refresh_token": "r",
             "client_id": "c", "client_secret": "s"})
        g._load_or_get_credentials = lambda: fake_creds
        g._build_services = lambda c: None
        g.authorize()
        assert g._ready is True

    def test_missing_credentials_file(self, tmp_path):
        """Нет credentials.json → GoogleOAuthError."""
        g = GoogleTasks(
            credentials_file=str(tmp_path / "missing.json"),
            token_file=str(tmp_path / "token.json"))
        with pytest.raises(Exception):
            g._load_or_get_credentials()

    def test_is_ready_false_when_tasks_scope_missing(self, tmp_path):
        """Валидный calendar-only токен НЕ готов для Tasks."""
        tok = tmp_path / "token.json"
        _write_token(tok, ["https://www.googleapis.com/auth/calendar.events"])
        g = GoogleTasks(
            token_file=str(tok),
            credentials_file=str(tmp_path / "creds.json"))
        assert g.is_ready() is False

    def test_is_ready_true_when_tasks_scope_present(self, tmp_path):
        """Токен со scope tasks готов."""
        tok = tmp_path / "token.json"
        _write_token(tok, [
            "https://www.googleapis.com/auth/tasks",
            "https://www.googleapis.com/auth/calendar.events",
        ])
        g = GoogleTasks(
            token_file=str(tok),
            credentials_file=str(tmp_path / "creds.json"))
        assert g.is_ready() is True

    def test_missing_scope_triggers_reauth(self, tmp_path):
        """Нехватка scope → не возвращаем валидный токен, а идём в flow."""
        tok = tmp_path / "token.json"
        _write_token(tok, ["https://www.googleapis.com/auth/calendar.events"])
        g = GoogleTasks(
            token_file=str(tok),
            credentials_file=str(tmp_path / "missing.json"))
        with pytest.raises(GoogleOAuthError):
            g._load_or_get_credentials()


class TestOperations:
    """Операции с API."""

    def _google(self):
        g = GoogleTasks()
        g._tasks_service = FakeService()
        g._ready = True
        return g

    def test_create_task_creates_item_in_default_list(self):
        """create_task создаёт задачу в списке по умолчанию."""
        g = self._google()
        task_id = g.create_task("купить хлеб")
        assert task_id == "task-1"
        assert len(g._tasks_service.created) == 1
        task = g._tasks_service.created[0]
        assert task["title"] == "купить хлеб"
        assert "notes" not in task

    def test_create_task_with_notes(self):
        """create_task передаёт notes, если они заданы."""
        g = self._google()
        g.create_task("купить хлеб", notes="бородинский")
        task = g._tasks_service.created[0]
        assert task["notes"] == "бородинский"

    def test_create_task_empty_title(self):
        """Пустой текст → GoogleOAuthError."""
        g = self._google()
        with pytest.raises(GoogleOAuthError):
            g.create_task("  ")

    def test_not_ready_authorizes(self):
        """Если не ready — authorize() вызывается."""
        g = self._google()
        g._ready = False
        g.authorize = lambda: None
        g.create_task("тест")

    def test_list_tasks_returns_items(self):
        """list_tasks возвращает список незавершённых задач."""
        g = self._google()
        g.create_task("первая")
        g.create_task("вторая")
        tasks = g.list_tasks()
        assert [t["title"] for t in tasks] == ["первая", "вторая"]
        assert all(t["status"] == "needsAction" for t in tasks)

    def test_list_tasks_show_completed(self):
        """list_tasks(show_completed=True) отдаёт и завершённые."""
        g = self._google()
        g.create_task("первая")
        g._tasks_service.tasks()._tasks[0]["status"] = "completed"
        assert g.list_tasks(show_completed=False) == []
        assert [t["title"] for t in g.list_tasks(show_completed=True)] == \
            ["первая"]

    def test_complete_task_marks_done(self):
        """complete_task проставляет status=completed через patch."""
        g = self._google()
        task_id = g.create_task("помыть посуду")
        updated = g.complete_task(task_id)
        assert updated["status"] == "completed"
        assert [t["title"] for t in g.list_tasks()] == []

    def test_complete_task_empty_id_returns_none(self):
        """Пустой task_id → None без обращения к API."""
        g = self._google()
        assert g.complete_task("") is None
