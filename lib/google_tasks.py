"""Интеграция с Google Tasks API через OAuth 2.0.

Голосовая команда «добавь задачу купить хлеб» создаёт задачу в Google
Tasks (список по умолчанию «@default»). В отличие от напоминаний в
Calendar, задача не привязана ко времени — это просто пункт списка.

Авторизация использует общий token.json с Calendar: при консенте здесь
запрашиваются ОБА scope (tasks + calendar.events), чтобы пере-авторизация
из-за задач не стёрла права, выданные для напоминаний.
"""

from json import loads
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from lib.google_calendar import GoogleOAuthError

# Общий scope: tasks — для задач, calendar.events — чтобы консент не
# сломал напоминания (token.json общий с Calendar).
SCOPES = [
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/calendar.events",
]

DEFAULT_TASKLIST_ID = "@default"


class GoogleTasks:
    """Обёртка над Tasks API.

    Лениво инициализирует сервис при первом обращении; если token.json
    нет или не покрывает нужные scope — поднимает GoogleOAuthError.
    """

    def __init__(
        self,
        credentials_file: str = "credentials.json",
        token_file: str = "token.json",
        tasklist_id: str = DEFAULT_TASKLIST_ID,
    ) -> None:
        self._credentials_file = credentials_file
        self._token_file = token_file
        self._tasklist_id = tasklist_id
        self._tasks_service: Any = None
        self._ready = False

    # ---------- Авторизация ----------

    def authorize(self) -> None:
        """Проходит OAuth-флоу (если нужно) и готовит сервис."""
        creds = self._load_or_get_credentials()
        self._build_services(creds)
        self._ready = True

    def _load_or_get_credentials(self) -> Credentials:
        creds = None
        token_path = Path(self._token_file)
        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    self._token_file, SCOPES)
            except Exception:
                creds = None

        usable = creds is not None and self._token_has_scopes()
        if usable:
            if creds.valid:
                return creds
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    self._save_token(creds)
                    if self._token_has_scopes():
                        return creds
                except Exception:
                    pass

        if not Path(self._credentials_file).exists():
            raise GoogleOAuthError(
                f"Нет {self._credentials_file} — создай OAuth client в "
                "Google Cloud Console и скачай JSON сюда.")
        flow = InstalledAppFlow.from_client_secrets_file(
            self._credentials_file, SCOPES)
        try:
            creds = flow.run_local_server(port=0, open_browser=True)
        except Exception as e:
            raise GoogleOAuthError(f"Авторизация не удалась: {e}") from e
        self._save_token(creds)
        return creds

    def _token_has_scopes(self) -> bool:
        """Покрывает ли token.json все нужные SCOPES (по файлу)."""
        try:
            data = loads(Path(self._token_file).read_text(
                encoding="utf-8"))
        except Exception:
            return False
        granted = set(data.get("scopes") or [])
        return set(SCOPES).issubset(granted)

    def _save_token(self, creds: Credentials) -> None:
        with open(self._token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    def _build_services(self, creds: Credentials) -> None:
        import googleapiclient.discovery
        self._tasks_service = googleapiclient.discovery.build(
            "tasks", "v1", credentials=creds)

    # ---------- Публичные операции ----------

    def create_task(self, title: str, notes: Optional[str] = None) -> str:
        """Создаёт задачу в списке по умолчанию. Возвращает id задачи."""
        self._ensure_ready()
        if not title.strip():
            raise GoogleOAuthError("Пустой текст задачи")
        body = {"title": title}
        if notes:
            body["notes"] = notes
        result = self._tasks_service.tasks().insert(
            tasklist=self._tasklist_id, body=body).execute()
        return str(result["id"])

    def list_tasks(self, show_completed: bool = False) -> list[dict]:
        """Возвращает задачи списка по умолчанию.

        По умолчанию — только незавершённые (showCompleted=False).
        Элемент: {"id", "title", "status", "completed"}.
        """
        self._ensure_ready()
        result = self._tasks_service.tasks().list(
            tasklist=self._tasklist_id,
            showCompleted=show_completed).execute()
        return list(result.get("items", []))

    def complete_task(self, task_id: str) -> Optional[dict]:
        """Отмечает задачу выполненной (status=completed).

        Возвращает обновлённую задачу из API или None при пустом id.
        """
        if not task_id:
            return None
        self._ensure_ready()
        result = self._tasks_service.tasks().patch(
            tasklist=self._tasklist_id,
            task=task_id,
            body={"status": "completed"},
        ).execute()
        return result

    # ---------- Служебное ----------

    def is_ready(self) -> bool:
        """Авторизованы ли (есть валидный token.json с нужными scope)."""
        token_path = Path(self._token_file)
        if not token_path.exists():
            return False
        try:
            creds = Credentials.from_authorized_user_file(
                self._token_file, SCOPES)
            return bool(creds and creds.valid and self._token_has_scopes())
        except Exception:
            return False

    def _ensure_ready(self) -> None:
        if not self._ready:
            self.authorize()
