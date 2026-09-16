"""Интеграция с Google Calendar через OAuth 2.0.

Голосовые напоминания создаются как события календаря: «напомни мне
через 3 часа постирать бельё» → событие в календаре на указанное время
со всплывающим напоминанием.

Авторизация однократная: пользователь открывает URL-согласия в браузере,
приложение получает токен и сохраняет `token.json` (refresh-token).
Если `token.json` истёк/невалиден — авто-рефреш; при отсутствии
файла создаётся ссылка на авторизацию и поднимается GoogleOAuthError.

Примечание: Google Tasks API не хранит время задачи (due → всегда
полночь), поэтому напоминания целиком живут в Calendar.
"""

from datetime import datetime, timedelta
from json import loads
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
]

DEFAULT_REMINDER_MINUTES = 0
EVENT_DURATION_MINUTES = 30


class GoogleOAuthError(RuntimeError):
    """Ошибка авторизации или отсутствия доступа к Google API."""


class GoogleCalendar:
    """Обёртка над Calendar API.

    Лениво инициализирует сервис при первом обращении; если token.json
    нет или протух — поднимает GoogleOAuthError с инструкцией.
    """

    def __init__(
        self,
        credentials_file: str = "credentials.json",
        token_file: str = "token.json",
        calendar_id: str = "primary",
    ) -> None:
        self._credentials_file = credentials_file
        self._token_file = token_file
        self._calendar_id = calendar_id
        self._calendar_service: Any = None
        self._ready = False

    # ---------- Авторизация ----------

    def authorize(self) -> None:
        """Проходит OAuth-флоу (если нужно) и готовит сервисы.

        Если token.json не существует или не покрывает нужные scope —
        открывает consent-страницу в браузере через run_local_server.
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

        # Токен пригоден только если у него ЕСТЬ нужные scope: `creds.valid`
        # проверяет лишь срок, а не набор scope (Tasks-токен без calendar
        # молча бы прошёл и упал на API с 403).
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

        # Нет токена, протух, сломан рефреш или не хватает scope —
        # нужна новая интерактивная авторизация.
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
        """Покрывает ли token.json все нужные SCOPES.

        Читаем поле `scopes` из самого файла — у Credentials после
        from_authorized_user_file(..., scopes=...) оно равно аргументу
        конструктора, а не реально выданным правам.
        """
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
        self._calendar_service = googleapiclient.discovery.build(
            "calendar", "v3", credentials=creds)

    # ---------- Публичные операции ----------

    def create_reminder(
        self,
        summary: str,
        when: datetime,
        reminder_minutes: int = DEFAULT_REMINDER_MINUTES,
    ) -> str:
        """Создаёт событие-напоминание в календаре.

        Событие длится EVENT_DURATION_MINUTES, за reminder_minutes минут
        до начала показывается всплывающее напоминание (по умолчанию —
        в момент начала). Возвращает id события.
        """
        self._ensure_ready()
        if not summary.strip():
            raise GoogleOAuthError("Пустой текст напоминания")
        if when.tzinfo is None:
            when = when.astimezone()
        end = when + timedelta(minutes=EVENT_DURATION_MINUTES)
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

    def pending_events(self, limit: int = 50) -> list[dict]:
        """Актуальные события: текущие и ближайшие в будущее.

        Возвращает список событий, отсортированных по времени начала,
        без завершённых. Каждый элемент: id, summary, start, end —
        aware datetime (в локальной таймзоне). Для событий «весь день»
        время начала/конца — 00:00. Удобно для «что сейчас по планам».
        """
        events = self.list_events(limit=limit)
        now = datetime.now().astimezone()
        result = []
        for ev in events:
            start = self._parse_event_datetime(ev.get("start"))
            end = self._parse_event_datetime(ev.get("end"))
            if start is None:
                continue
            if end is None:
                end = start
            if start.tzinfo is None:
                start = start.astimezone()
            if end.tzinfo is None:
                end = end.astimezone()
            # Если событие уже закончилось — пропускаем.
            if end < now:
                continue
            result.append({
                "id": ev.get("id", ""),
                "summary": ev.get("summary", ""),
                "start": start,
                "end": end,
            })
        result.sort(key=lambda e: e["start"])
        return result

    @staticmethod
    def _parse_event_datetime(value: str) -> Optional[datetime]:
        """Парсит RFC3339 или дату из события. None если не парсится."""
        if not value:
            return None
        val = value.strip()
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            try:
                return datetime.strptime(val, "%Y-%m-%d")
            except ValueError:
                return None

    def list_events(self, limit: int = 25) -> list[dict[str, str]]:
        """Ближайшие события календаря от текущего момента.

        Каждое событие: id, summary, start (RFC3339 или дата).
        Сортировка — по времени начала.
        """
        self._ensure_ready()
        now = datetime.utcnow()
        events = self._calendar_service.events().list(
            calendarId=self._calendar_id,
            timeMin=now.isoformat() + "Z",
            maxResults=limit,
            singleEvents=True,
            orderBy="startTime",
        ).execute().get("items", [])
        result = []
        for ev in events:
            start = (ev.get("start") or {}).get(
                "dateTime", (ev.get("start") or {}).get("date", ""))
            end = (ev.get("end") or {}).get(
                "dateTime", (ev.get("end") or {}).get("date", ""))
            result.append({
                "id": str(ev.get("id", "")),
                "summary": ev.get("summary", ""),
                "start": start,
                "end": end,
            })
        return result

    # ---------- Служебное ----------

    def is_ready(self) -> bool:
        """Авторизованы ли (есть валидный token.json с нужными scope).

        Проверяем и срок, и набор scope: токен без calendar.events
        считается НЕ готовым, чтобы принудительно переавторизоваться.
        """
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


def _main(argv: Any = None) -> int:
    """CLI: `python -m lib.google_calendar list [--limit N] [--out file]`.

    `--out file` пишет результат в UTF-8 файл (удобно при чтении из
    консоли с cp866, где кириллица отображается кракозябрами).
    """
    import argparse
    parser = argparse.ArgumentParser(
        prog="python -m lib.google_calendar",
        description="Работа с Google Calendar")
    sub = parser.add_subparsers(dest="cmd", required=True)
    list_p = sub.add_parser("list", help="показать ближайшие события")
    list_p.add_argument("--limit", type=int, default=25)
    list_p.add_argument("--out", help="записать вывод в файл (UTF-8)")
    args = parser.parse_args(argv)

    events = GoogleCalendar().list_events(limit=args.limit)
    lines = [
        f"{e['start']:<32} {e['summary']}"
        for e in events
    ]
    output = "\n".join(lines) if lines else "(нет событий)"
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
