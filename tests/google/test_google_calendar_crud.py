"""Тесты Google Calendar: get_event / delete_event / патчи событий (CRUD по id)."""


from datetime import datetime

from lib.google_calendar import GoogleCalendar


class _Req:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _Events:
    def __init__(self, get_result=None, get_error=False, delete_error=False,
                 patch_error=False):
        self.get_result = get_result
        self.get_error = get_error
        self.delete_error = delete_error
        self.patch_error = patch_error
        self.deleted = []
        self.patched = []

    def get(self, **kw):
        if self.get_error:
            raise RuntimeError("404 not found")
        return _Req(self.get_result)

    def delete(self, **kw):
        if self.delete_error:
            raise RuntimeError("boom")
        self.deleted.append(kw.get("eventId"))
        return _Req(None)

    def patch(self, **kw):
        if self.patch_error:
            raise RuntimeError("403")
        self.patched.append((kw.get("eventId"), kw.get("body")))
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


def test_set_event_summary_patches_only_summary():
    """Переименование задевает только summary: время и цвет остаются."""
    g = _google()
    assert g.set_event_summary("e1", "Отдых") is True
    assert g._calendar_service.events().patched == [
        ("e1", {"summary": "Отдых"})]


def test_set_event_summary_error_returns_false():
    """Сбой patch — False, исключения наружу нет."""
    assert _google(patch_error=True).set_event_summary("e1", "Отдых") is False


def test_set_event_color_patches_only_color():
    """Галочка «сделано» ставится патчем одного colorId."""
    g = _google()
    assert g.set_event_color("e1", 7) is True
    assert g._calendar_service.events().patched == [("e1", {"colorId": "7"})]


_E1 = {"id": "e1", "summary": "план",
       "start": {"dateTime": "2026-09-15T14:00:00+04:00"},
       "end": {"dateTime": "2026-09-15T14:30:00+04:00"}}


def test_update_event_start_patches_only_start():
    """Команда «спать» двигает начало, конец события остаётся."""
    g = _google(get_result=_E1)
    new = datetime.fromisoformat("2026-09-15T13:00:00+04:00")
    assert g.update_event_start("e1", new) is True
    assert g._calendar_service.events().patched == [
        ("e1", {"start": {"dateTime": new.isoformat()}})]


def test_update_event_start_after_end_is_rejected():
    """Начало позже конца — Google не примет, запроса не будет."""
    g = _google(get_result=_E1)
    late = datetime.fromisoformat("2026-09-15T15:00:00+04:00")
    assert g.update_event_start("e1", late) is False
    assert g._calendar_service.events().patched == []


def test_update_event_end_of_all_day_is_rejected():
    """Событие «весь день» (дата без времени) не двигается."""
    g = _google(get_result={"id": "e2", "start": {"date": "2026-09-16"},
                            "end": {"date": "2026-09-17"}})
    assert g.update_event_end("e2", datetime.now()) is False
    assert g._calendar_service.events().patched == []


def test_update_event_end_ok():
    """Пробуждение фиксирует конец «СОН» патчем только end."""
    g = _google(get_result=_E1)
    new = datetime.fromisoformat("2026-09-15T14:20:00+04:00")
    assert g.update_event_end("e1", new) is True
    assert g._calendar_service.events().patched == [
        ("e1", {"end": {"dateTime": new.isoformat()}})]
