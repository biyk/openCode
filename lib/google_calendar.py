"""Интеграция с Google Calendar и Google Tasks через OAuth 2.0.

Позволяет голосовому ассистенту создавать напоминания: задача попадает
в Google Tasks (список «По умолчанию») и событие в Google Calendar
на указанное время, чтобы на телефоне/ноутбуке пришло уведомление.

Авторизация однократная: пользователь открывает URL-согласия в браузере,
приложение получает токен и сохраняет `token.json` (refresh-token).
Оффлайн: если `token.json` истёк/невалиден — попытка пересоздать
ссылку на авторизацию и вернуть ошибку.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
]

DEFAULT_REMINDER_MINUTES = 10


class GoogleOAuthError(RuntimeError):
    """Ошибка авторизации или отсутствия доступа к Google API."""


class GoogleCalendar:
    """Обёртка над Calendar + Tasks API.

    Лениво инициализирует сервисы при первом обращении; если token.json
    нет или протух — поднимает GoogleOAuthError с инструкцией.
    """

    def __init__(
        self,
        credentials_file: str = "credentials.json",
        token_file: str = "token.json",
        calendar_id: str = "primary",
        tasks_list_id: str = "default",
    ) -> None:
        self._credentials_file = credentials_file
        self._token_file = token_file
        self._calendar_id = calendar_id
        self._tasks_list_id = tasks_list_id
        self._calendar_service: Any = None
        self._tasks_service: Any = None
        self._ready = False

    # ---------- Авторизация ----------

    def authorize(self) -> None:
        """Проходит OAuth-флоу (если нужно) и готовит сервисы.

        Если token.json не существует — открывает consent-страницу в
        браузере через run_local_server и сохраняет токен.
        """
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
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self._save_token(creds)
            return creds
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

    def _save_token(self, creds: Credentials) -> None:
        with open(self._token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    def _build_services(self, creds: Credentials) -> None:
        import googleapiclient.discovery
        self._calendar_service = googleapiclient.discovery.build(
            "calendar", "v3", credentials=creds)
        self._tasks_service = googleapiclient.discovery.build(
            "tasks", "v1", credentials=creds)
        if self._tasks_list_id == "default":
            self._tasks_list_id = self._resolve_default_tasks_list()

    def _resolve_default_tasks_list(self) -> str:
        """Находит id «Списка по умолчанию» (или «Мои задачи») в Tasks."""
        items = (self._tasks_service.tasklists().list()
                 .execute().get("items", []))
        if not items:
            raise GoogleOAuthError("В Google Tasks нет списков")
        for item in items:
            title = item.get("title", "")
            if title in ("Список по умолчанию", "My Tasks", "Мои задачи"):
                return str(item["id"])
        return str(items[0]["id"])

    # ---------- Публичные операции ----------

    def create_reminder(
        self,
        summary: str,
        when: datetime,
        reminder_minutes: int = DEFAULT_REMINDER_MINUTES,
    ) -> dict[str, str]:
        """Создаёт задачу в Tasks и событие в Calendar.

        Возвращает {"task": task_id, "event": event_id}.
        """
        self._ensure_ready()
        if not summary.strip():
            raise GoogleOAuthError("Пустой текст напоминания")
        task_id = self._create_task(summary, when)
        event_id = self._create_event(summary, when, reminder_minutes)
        return {"task": task_id, "event": event_id}

    def _create_task(self, summary: str, when: datetime) -> str:
        if when.tzinfo is None:
            when = when.astimezone()
        body = {"title": summary, "due": when.isoformat()}
        result = self._tasks_service.tasks().insert(
            tasklist=self._tasks_list_id, body=body).execute()
        return str(result["id"])

    def _create_event(
        self, summary: str, when: datetime, reminder_minutes: int,
    ) -> str:
        if when.tzinfo is None:
            when = when.astimezone()
        end = when + timedelta(minutes=30)
        body = {
            "summary": summary,
            "start": {"dateTime": when.isoformat()},
            "end": {"dateTime": end.isoformat()},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": reminder_minutes},
                ],
            },
        }
        result = self._calendar_service.events().insert(
            calendarId=self._calendar_id, body=body).execute()
        return str(result["id"])

    def list_upcoming(self, hours: int = 24) -> list[dict[str, str]]:
        """Ближайшие события календаря до hours часов вперёд."""
        self._ensure_ready()
        now = datetime.utcnow()
        end = now + timedelta(hours=hours)
        events = self._calendar_service.events().list(
            calendarId=self._calendar_id,
            timeMin=now.isoformat() + "Z",
            timeMax=end.isoformat() + "Z",
            singleEvents=True,
            orderBy="startTime",
        ).execute().get("items", [])
        result = []
        for ev in events:
            start = ev.get("start", {}).get("dateTime",
                                            ev.get("start", {}).get("date", ""))
            result.append({"summary": ev.get("summary", ""), "start": start})
        return result

    # ---------- Служебное ----------

    def is_ready(self) -> bool:
        """Авторизованы ли (есть валидный token.json)."""
        token_path = Path(self._token_file)
        if not token_path.exists():
            return False
        try:
            creds = Credentials.from_authorized_user_file(
                self._token_file, SCOPES)
            return bool(creds and creds.valid)
        except Exception:
            return False

    def _ensure_ready(self) -> None:
        if not self._ready:
            self.authorize()
