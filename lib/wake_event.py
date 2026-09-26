"""Голосовая команда «я проснулся»: фиксирует конец события «СОН» в календаре.

Ищет в Google Calendar ближайшее мероприятие с названием «СОН», которое
НАЧАЛОСЬ до момента произнесения команды (т.е. сон, от которого
проснулись), и меняет ему только дату завершения на текущий момент
(время начала не трогает). Т.е. команда отмечает, во сколько сон
реально закончился.

CLI: `python -m lib.wake_event`. Коды выхода: 0 — конец зафиксирован,
1 — событие не найдено или запрос к календарю не прошёл.
"""

from datetime import datetime, timedelta
from typing import Optional

from lib.google_calendar import GoogleCalendar
from lib.google.google_calendar_events import GoogleCalendarEventsMixin
from lib.sleep_event import SLEEP_TITLE_RE

# Сон, от которого просыпаются, начался не дальше суток назад.
LOOKBACK = timedelta(hours=24)
# Небольшой зазор в будущее: «началось до момента» округляем по now.
LOOKAHEAD = timedelta(hours=1)


class WakeEventHandler:
    """Находит начавшийся «СОН» и переносит его конец на текущий момент."""

    def __init__(self, google: Optional[GoogleCalendar] = None,
                 now: Optional[datetime] = None) -> None:
        self._google = google or GoogleCalendar()
        self._now = now

    @property
    def now(self) -> datetime:
        """Текущее время (для тестов — фиксированное)."""
        return self._now if self._now is not None else datetime.now().astimezone()

    def find_started_sleep_event(self) -> Optional[dict]:
        """«СОН», начавшийся раньше всего недавнего момента.

        Среди событий с названием «СОН», начало которых строго до
        текущего времени, берётся самое позднее по началу — то, от
        которого проснулись сейчас.
        """
        events = self._google.list_events_between(
            self.now - LOOKBACK, self.now + LOOKAHEAD)
        now = self.now
        candidates = []
        for ev in events:
            if not SLEEP_TITLE_RE.search(ev.get("summary") or ""):
                continue
            start = GoogleCalendarEventsMixin._parse_event_datetime(
                ev.get("start"))
            if start is None:
                continue
            if start.tzinfo is None:
                start = start.astimezone()
            if start >= now:
                continue  # ещё не началось
            candidates.append((start, ev))
        if not candidates:
            return None
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return candidates[0][1]

    def fix_wake_end(self) -> Optional[dict]:
        """Меняет конец «СНА» на сейчас (начало не трогает).

        None — если не удалось.
        """
        ev = self.find_started_sleep_event()
        if ev is None:
            return None
        if not self._google.update_event_end(ev["id"], self.now):
            return None
        ev["end"] = self.now.isoformat()
        return ev


def _main(argv: Optional[list[str]] = None) -> int:
    handler = WakeEventHandler()
    try:
        ev = handler.fix_wake_end()
    except Exception as e:  # нет токена/сети — сообщаем и падаем
        print(f"[wake] ошибка календаря: {e}")
        return 1
    if ev is None:
        print("[wake] начавшееся событие «СОН» не найдено")
        return 1
    print(f"[wake] конец «{ev['summary']}» перенесён на "
          f"{handler.now:%d.%m.%Y %H:%M}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
