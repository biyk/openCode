"""Обработчик голосового запроса «что у меня сейчас по планам».

Берёт из Google Calendar актуальное событие (текущее или ближайшее
открытое) и отдаёт его для озвучки. Время разбирается из календаря
детерминированно: сначала — идущее прямо сейчас событие, иначе —
самое близкое будущее.
"""

import re
from datetime import datetime, timedelta
from typing import Optional

from lib.google_calendar import GoogleCalendar

TRIGGER_PHRASES = (
    "что у меня сейчас по планам",
    "что сейчас по планам",
    "что у меня по планам",
    "что по планам",
    "какие у меня планы",
    "какие у меня сейчас планы",
    "что у меня в планах",
    "что я должен делать сейчас",
    "что мне сейчас делать",
)

# «по расписанию» — часто распознаётся Vosk с искажениями: «по расписание»,
# «по расписане», а иногда Vosk съедает приставку «ра» («про списанию»,
# т.е. банковское «списание»). Достаточно попадания в основу слова.
_SCHEDULE_RE = re.compile(r"\b(?:ра)?списан\w*\b", re.IGNORECASE)

NEAR_PAST_WINDOW_MINUTES = 15


def normalize(text: str) -> str:
    """Нижний регистр, ё→е, схлопывание пробелов."""
    return " ".join(text.lower().replace("ё", "е").split())


class PlansHandler:
    """Определяет запрос планов и находит актуальную задачу."""

    def __init__(self, google: Optional[GoogleCalendar] = None,
                 now: Optional[datetime] = None) -> None:
        self._google = google or GoogleCalendar()
        self._now = now

    @property
    def now(self) -> datetime:
        """Текущее время (для тестов — фиксированное)."""
        return self._now if self._now is not None else datetime.now().astimezone()

    def is_plans_query(self, text: str) -> bool:
        """Является ли текст запросом планов (или расписания)."""
        t = normalize(text)
        if any(p in t for p in TRIGGER_PHRASES):
            return True
        return bool(_SCHEDULE_RE.search(text))

    def auth_ready(self) -> bool:
        """Готовы ли авторизация и scope для Calendar."""
        return self._google.is_ready()

    def current_task(self) -> Optional[dict]:
        """Возвращает актуальную задачу (id, summary, start, end) или None.

        Приоритет: событие, которое идёт прямо сейчас (началось не более
        NEAR_PAST_WINDOW_MINUTES назад); иначе — ближайшее будущее.
        """
        events = self._google.pending_events(limit=50)
        if not events:
            return None
        events = sorted(events, key=lambda e: e["start"])
        now = self.now
        # Идущее сейчас событие (началось в окне недавнего прошлого / уже идёт).
        for ev in events:
            start, end = ev["start"], ev["end"]
            if start <= now <= end or (start < now and now - start <= timedelta(
                    minutes=NEAR_PAST_WINDOW_MINUTES)):
                return ev
        # Иначе — ближайшее будущее событие.
        future = [e for e in events if e["start"] >= now]
        if future:
            return future[0]
        return None
