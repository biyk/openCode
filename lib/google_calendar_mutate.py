"""Мутации событий Google Calendar (миксин): перенос начала, удаление."""

from datetime import datetime


class GoogleCalendarMutateMixin:
    """Миксин GoogleCalendar: изменение существующих событий."""

    def update_event_start(self, event_id: str, new_start: datetime) -> bool:
        """Меняет ТОЛЬКО дату начала события; конец остаётся как был.

        False — если событие «весь день» (нет времени), new_start не
        раньше конца или запрос не прошёл.
        """
        self._ensure_ready()
        try:
            ev = self._calendar_service.events().get(
                calendarId=self._calendar_id, eventId=event_id).execute()
        except Exception:
            return False
        start_raw = (ev.get("start") or {}).get("dateTime")
        end_raw = (ev.get("end") or {}).get("dateTime")
        if not start_raw or not end_raw:
            return False
        try:
            end = datetime.fromisoformat(end_raw)
        except ValueError:
            return False
        if new_start.tzinfo is None:
            new_start = new_start.astimezone()
        if new_start >= end.astimezone(new_start.tzinfo):
            return False  # начало позже конца — Google не примет
        body = {"start": {"dateTime": new_start.isoformat()}}
        try:
            self._calendar_service.events().patch(
                calendarId=self._calendar_id, eventId=event_id,
                body=body).execute()
        except Exception:
            return False
        return True

    def delete_event(self, event_id: str) -> bool:
        """Удаляет событие по id. True — если запрос прошёл."""
        self._ensure_ready()
        try:
            self._calendar_service.events().delete(
                calendarId=self._calendar_id, eventId=event_id).execute()
            return True
        except Exception:
            return False
