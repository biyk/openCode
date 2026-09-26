"""Мутации событий Google Calendar (миксин): перенос начала/конца, удаление."""

from datetime import datetime, timedelta
from typing import Optional

from lib.core.errors import swallowed

# Цвет «галочки» выполнения того же JS-приложения (done.md §0).
DONE_COLOR = "7"


class GoogleCalendarMutateMixin:
    """Миксин GoogleCalendar: изменение существующих событий."""

    def put_done_event(self, summary: str, description: str, minutes: int,
                       end: datetime, event_id: Optional[str] = None) -> str:
        """Создаёт/обновляет событие-«галочку» (colorId=7) длительностью minutes.

        Интервал — [end − minutes, end]: выполнение засчитывается по плану
        и оканчивается в момент нажатия (done.md §7). Без event_id вставляет
        новое событие, с event_id — обновляет существующее (так JS-клиент
        превращает запланированное событие задачи в галочку). Пустая строка
        — запрос не прошёл.
        """
        self._ensure_ready()
        if end.tzinfo is None:
            end = end.astimezone()
        start = end - timedelta(minutes=max(1, int(minutes)))
        body = {
            "summary": summary,
            "description": description,
            "colorId": DONE_COLOR,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        try:
            events = self._calendar_service.events()
            if event_id:
                ev = events.update(calendarId=self._calendar_id,
                                   eventId=event_id, body=body).execute()
            else:
                ev = events.insert(calendarId=self._calendar_id,
                                   body=body).execute()
        except Exception as e:
            return swallowed("gcal.put_done_event", e, "")
        return str(ev.get("id", ""))

    def update_event_start(self, event_id: str, new_start: datetime) -> bool:
        """Меняет ТОЛЬКО дату начала события; конец остаётся как был.

        False — если событие «весь день» (нет времени), new_start не
        раньше конца или запрос не прошёл.
        """
        self._ensure_ready()
        try:
            ev = self._calendar_service.events().get(
                calendarId=self._calendar_id, eventId=event_id).execute()
        except Exception as e:
            return swallowed("gcal.update_event_start.get", e, False)
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
        except Exception as e:
            return swallowed("gcal.update_event_start.patch", e, False)
        return True

    def update_event_end(self, event_id: str, new_end: datetime) -> bool:
        """Меняет ТОЛЬКО дату завершения события; начало остаётся как был.

        False — если событие «весь день» (нет времени), new_end не
        позже начала или запрос не прошёл.
        """
        self._ensure_ready()
        try:
            ev = self._calendar_service.events().get(
                calendarId=self._calendar_id, eventId=event_id).execute()
        except Exception as e:
            return swallowed("gcal.update_event_end.get", e, False)
        start_raw = (ev.get("start") or {}).get("dateTime")
        end_raw = (ev.get("end") or {}).get("dateTime")
        if not start_raw or not end_raw:
            return False
        try:
            start = datetime.fromisoformat(start_raw)
        except ValueError:
            return False
        if new_end.tzinfo is None:
            new_end = new_end.astimezone()
        if new_end <= start.astimezone(new_end.tzinfo):
            return False  # конец раньше начала — Google не примет
        body = {"end": {"dateTime": new_end.isoformat()}}
        try:
            self._calendar_service.events().patch(
                calendarId=self._calendar_id, eventId=event_id,
                body=body).execute()
        except Exception as e:
            return swallowed("gcal.update_event_end.patch", e, False)
        return True

    def delete_event(self, event_id: str) -> bool:
        """Удаляет событие по id. True — если запрос прошёл."""
        self._ensure_ready()
        try:
            self._calendar_service.events().delete(
                calendarId=self._calendar_id, eventId=event_id).execute()
            return True
        except Exception as e:
            return swallowed("gcal.delete_event", e, False)
