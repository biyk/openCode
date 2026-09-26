"""Голосовая команда «спать»: фиксирует начало события «СОН» в календаре.

Ищет в Google Calendar мероприятие с названием «СОН», которое скоро
начнётся или уже идёт, и меняет ему только дату начала на текущий
момент (время окончания не трогает). Т.е. команда отмечает, во сколько
сон реально начался.

CLI: `python -m lib.sleep_event` — вызывается как шаг sequence `sleepmode`
после опускания громкости. Коды выхода: 0 — начало зафиксировано,
1 — событие не найдено или запрос к календарю не прошёл.
"""

import re
from datetime import datetime, timedelta
from typing import Optional

from lib.google_calendar import GoogleCalendar
from lib.google.google_calendar_events import GoogleCalendarEventsMixin

# «СОН» как отдельное слово в заголовке (регистр не важен, ё=е).
SLEEP_TITLE_RE = re.compile(r"\bсон\b", re.IGNORECASE)

# Окно поиска: «уже идёт» могло начаться вчера вечером; «скоро
# начнётся» — в пределах суток (событие «СОН» создают на сегодня/завтра).
LOOKBACK = timedelta(hours=12)
LOOKAHEAD = timedelta(hours=24)


class SleepEventHandler:
    """Находит событие «СОН» и переносит его начало на текущий момент."""

    def __init__(self, google: Optional[GoogleCalendar] = None,
                 now: Optional[datetime] = None) -> None:
        self._google = google or GoogleCalendar()
        self._now = now

    @property
    def now(self) -> datetime:
        """Текущее время (для тестов — фиксированное)."""
        return self._now if self._now is not None else datetime.now().astimezone()

    def find_sleep_event(self) -> Optional[dict]:
        """Событие «СОН», идущее сейчас или ближайшее из будущих.

        Завершившиеся события не рассматриваются. Среди кандидатов
        берётся самое раннее по началу — оно и есть «то, что идёт».
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
            end = GoogleCalendarEventsMixin._parse_event_datetime(
                ev.get("end"))
            if start is None or end is None:
                continue
            if start.tzinfo is None:
                start = start.astimezone()
            if end.tzinfo is None:
                end = end.astimezone()
            if end < now:
                continue  # уже завершилось
            candidates.append((start, ev))
        if not candidates:
            return None
        candidates.sort(key=lambda pair: pair[0])
        return candidates[0][1]

    def fix_sleep_start(self) -> Optional[dict]:
        """Меняет начало «СНА» на сейчас (конец не трогает).

        None — если не удалось.
        """
        ev = self.find_sleep_event()
        if ev is None:
            return None
        if not self._google.update_event_start(ev["id"], self.now):
            return None
        ev["start"] = self.now.isoformat()
        return ev


def _main(argv: Optional[list[str]] = None) -> int:
    handler = SleepEventHandler()
    try:
        ev = handler.fix_sleep_start()
    except Exception as e:  # нет токена/сети — сообщаем и падаем
        print(f"[sleep] ошибка календаря: {e}")
        return 1
    if ev is None:
        print("[sleep] событие «СОН» (идущее или ближайшее) не найдено")
        return 1
    print(f"[sleep] начало «{ev['summary']}» перенесено на "
          f"{handler.now:%d.%m.%Y %H:%M}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
