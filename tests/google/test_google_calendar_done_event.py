"""Тесты события-«галочки» colorId=7 (GoogleCalendar.put_done_event)."""

from datetime import datetime, timedelta, timezone

from lib.google_calendar import GoogleCalendar

TZ = timezone(timedelta(hours=3))
END = datetime(2026, 9, 26, 7, 30, tzinfo=TZ)


class _Req:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _Events:
    def __init__(self, error=False):
        self.error = error
        self.inserted = []
        self.updated = []

    def insert(self, **kw):
        if self.error:
            raise RuntimeError("403")
        self.inserted.append(kw)
        return _Req({"id": "new-1"})

    def update(self, **kw):
        if self.error:
            raise RuntimeError("404")
        self.updated.append(kw)
        return _Req({"id": kw.get("eventId")})


class _Service:
    def __init__(self, **kw):
        self._events = _Events(**kw)

    def events(self):
        return self._events


def _google(**kw):
    g = GoogleCalendar()
    g._calendar_service = _Service(**kw)
    g._ready = True
    return g


def test_insert_keeps_plan_duration_before_now():
    """Новая галочка: insert, интервал [end − minutes, end], colorId=7."""
    g = _google()
    event_id = g.put_done_event("Пробуждение", "uuid-1", 3, END)
    assert event_id == "new-1"
    body = g._calendar_service.events().inserted[0]["body"]
    assert body["colorId"] == "7"
    assert body["summary"] == "Пробуждение"
    assert body["description"] == "uuid-1"
    assert datetime.fromisoformat(body["end"]["dateTime"]) == END
    assert datetime.fromisoformat(body["start"]["dateTime"]) == END - timedelta(
        minutes=3)


def test_zero_and_negative_minutes_never_invert_the_interval():
    """Пустой план (task_time=0) — событие не «заднего числа»."""
    g = _google()
    g.put_done_event("Пробуждение", "uuid-1", 0, END)
    body = g._calendar_service.events().inserted[0]["body"]
    start = datetime.fromisoformat(body["start"]["dateTime"])
    assert start < END


def test_existing_event_is_updated_by_id():
    """С event_id — update того же события (плановое становится галочкой)."""
    g = _google()
    assert g.put_done_event("Пробуждение", "uuid-1", 3, END,
                            event_id="ev-1") == "ev-1"
    events = g._calendar_service.events()
    assert events.inserted == []
    assert events.updated[0]["eventId"] == "ev-1"


def test_naive_time_is_localized_and_api_error_returns_empty():
    """Без tzinfo время локализуем; сбой API — пустая строка (не исключение)."""
    g = _google(error=True)
    assert g.put_done_event("Пробуждение", "uuid-1", 3,
                            END.replace(tzinfo=None)) == ""
