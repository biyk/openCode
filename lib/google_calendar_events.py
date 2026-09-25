"""Операции с событиями Google Calendar (миксин)."""

from datetime import datetime, timedelta
from typing import Optional

from lib.google_calendar_mutate import GoogleCalendarMutateMixin

DEFAULT_REMINDER_MINUTES = 0
EVENT_DURATION_MINUTES = 30


class GoogleOAuthError(RuntimeError):
    """Ошибка авторизации или отсутствия доступа к Google API."""


class GoogleCalendarEventsMixin(GoogleCalendarMutateMixin):
    """Миксин GoogleCalendar: создание и чтение событий.

    Мутации существующих событий (update_event_start, delete_event) —
    в GoogleCalendarMutateMixin.
    """

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

    def list_events_between(
        self,
        time_min: datetime,
        time_max: datetime,
        limit: int = 50,
    ) -> list[dict[str, str]]:
        """События в окне [time_min, time_max] — тем же форматом, что list_events.

        Нужно, чтобы видеть и уже идущие события (у list_events нижняя
        граница — текущий момент).
        """
        self._ensure_ready()
        return self._list_events_raw(
            time_min.isoformat(), time_max.isoformat(), limit)

    def list_events(self, limit: int = 25) -> list[dict[str, str]]:
        """Ближайшие события календаря от текущего момента.

        Каждое событие: id, summary, start (RFC3339 или дата).
        Сортировка — по времени начала.
        """
        self._ensure_ready()
        now = datetime.utcnow()
        return self._list_events_raw(
            now.isoformat() + "Z", None, limit)

    def _list_events_raw(
        self,
        time_min: str,
        time_max: Optional[str],
        limit: int,
    ) -> list[dict[str, str]]:
        """Общий запрос events().list; time_min/time_max — RFC3339-строки."""
        kwargs = {
            "calendarId": self._calendar_id,
            "timeMin": time_min,
            "maxResults": limit,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_max:
            kwargs["timeMax"] = time_max
        events = self._calendar_service.events().list(**kwargs) \
            .execute().get("items", [])
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

    def get_event(self, event_id: str) -> Optional[dict]:
        """Возвращает событие по id или None, если его нет/недоступно.

        Формат элемента как у list_events: id, summary, start, end.
        """
        self._ensure_ready()
        try:
            ev = self._calendar_service.events().get(
                calendarId=self._calendar_id, eventId=event_id).execute()
        except Exception:
            return None
        if not ev or not ev.get("id"):
            return None
        # Удалённое событие Google помечает status=cancelled, но get его
        # ещё отдаёт — для «существует/не существует» считаем отменённые
        # отсутствующими.
        if str(ev.get("status", "")).lower() == "cancelled":
            return None
        start = (ev.get("start") or {}).get(
            "dateTime", (ev.get("start") or {}).get("date", ""))
        end = (ev.get("end") or {}).get(
            "dateTime", (ev.get("end") or {}).get("date", ""))
        return {
            "id": str(ev.get("id", "")),
            "summary": ev.get("summary", ""),
            "start": start,
            "end": end,
        }
