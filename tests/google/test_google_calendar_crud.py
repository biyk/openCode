"""Тесты Google Calendar: get_event / delete_event (CRUD по id)."""


from lib.google_calendar import GoogleCalendar


class _Req:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _Events:
    def __init__(self, get_result=None, get_error=False, delete_error=False):
        self.get_result = get_result
        self.get_error = get_error
        self.delete_error = delete_error
        self.deleted = []

    def get(self, **kw):
        if self.get_error:
            raise RuntimeError("404 not found")
        return _Req(self.get_result)

    def delete(self, **kw):
        if self.delete_error:
            raise RuntimeError("boom")
        self.deleted.append(kw.get("eventId"))
        return _Req(None)


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


def test_get_event_returns_event():
    """get_event мапит поля события по id."""
    g = _google(get_result={
        "id": "e1", "summary": "план",
        "start": {"dateTime": "2026-09-15T14:00:00+04:00"},
        "end": {"dateTime": "2026-09-15T14:30:00+04:00"}})
    assert g.get_event("e1") == {
        "id": "e1", "summary": "план",
        "start": "2026-09-15T14:00:00+04:00",
        "end": "2026-09-15T14:30:00+04:00"}


def test_get_event_all_day():
    """Событие «весь день» отдаёт дату без времени."""
    g = _google(get_result={
        "id": "e2", "summary": "аллдей",
        "start": {"date": "2026-09-16"}, "end": {"date": "2026-09-17"}})
    ev = g.get_event("e2")
    assert ev["start"] == "2026-09-16"
    assert ev["end"] == "2026-09-17"


def test_get_event_missing_returns_none():
    """Несуществующее событие → None."""
    assert _google(get_error=True).get_event("nope") is None


def test_get_event_without_id_returns_none():
    """Пустой ответ без id → None."""
    assert _google(get_result={}).get_event("x") is None


def test_get_event_cancelled_returns_none():
    """Удалённое (status=cancelled) событие считается отсутствующим."""
    g = _google(get_result={
        "id": "e1", "status": "cancelled", "summary": "удалённый",
        "start": {"dateTime": "2026-09-15T14:00:00+04:00"},
        "end": {"dateTime": "2026-09-15T14:30:00+04:00"}})
    assert g.get_event("e1") is None


def test_delete_event_ok():
    """delete_event удаляет событие и возвращает True."""
    g = _google()
    assert g.delete_event("e1") is True
    assert g._calendar_service.events().deleted == ["e1"]


def test_delete_event_error_returns_false():
    """Ошибка удаления → False."""
    assert _google(delete_error=True).delete_event("e1") is False
