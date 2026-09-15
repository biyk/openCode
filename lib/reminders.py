"""Обработчик голосовых команд напоминаний.

Связывает распознанный текст («напомни мне через 3 часа постирать
бельё») с Google Calendar через lib.google_calendar: каждое напоминание
становится событием календаря со всплывающим уведомлением.

Время разбирается детерминированным парсером (lib.time_parser),
LLM не используется. Если время во фразе не указано — напоминание
ставится через 60 минут от текущего момента.
"""

import re
from datetime import timedelta
from typing import Optional

from lib.google_calendar import GoogleCalendar
from lib.time_parser import ReminderSpec, TimeParseError, TimeParser

TRIGGER_PHRASES = (
    "напомним",
    "напомни",
    "поставь напоминание",
    "создай напоминание",
    "добавь напоминание",
    "запомнить",
)

DEFAULT_REMINDER_DELAY_MINUTES = 60

_FILLERS_RE = re.compile(
    r"^\s*(?:(?:мне|пожалуйста|алиса|прошу)\s+)*"
    r"(?:мне|пожалуйста|алиса|прошу)?\s*")


def _clean_candidate(text: str) -> str:
    """Убирает триггерную часть и слова-заполнители из фразы.

    Триггер срезается по границе слова («напомним» целиком, а не
    первые 6 букв), чтобы не оставался хвост вроде «м …» после
    ошибочного распознавания Vosk. Заполнители («мне пожалуйста»)
    убираются все подряд, иначе слово в начале мешает парсеру времени
    найти «через» в начале фразы.
    """
    t = text.lower().strip()
    for phrase in TRIGGER_PHRASES:
        if t.startswith(phrase):
            after = t[len(phrase):]
            # Оставляем только до границы слова (пробел/конец).
            if after and not after[0].isspace():
                continue
            t = after.strip()
            break
    t = _FILLERS_RE.sub("", t)
    t = re.sub(r"\s+пожалуйста\s*$", "", t)
    return t.strip()


class ReminderHandler:
    """Определяет, является ли текст напоминанием, и создаёт его."""

    def __init__(
        self,
        google: Optional[GoogleCalendar] = None,
        parser: Optional[TimeParser] = None,
    ) -> None:
        self._google = google or GoogleCalendar()
        self._parser = parser or TimeParser()

    def is_reminder(self, text: str) -> bool:
        """Начинается ли текст с триггерной фразы напоминания."""
        t = text.lower().strip()
        return any(t.startswith(p) for p in TRIGGER_PHRASES) or \
            bool(re.match(r"напомнишь\b", t))

    def create(self, text: str) -> Optional[ReminderSpec]:
        """Разбирает время и текст напоминания.

        Возвращает ReminderSpec; если время не распознано — время
        становится «через 60 минут», а текст — вся очищенная фраза.
        Возвращает None только для пустой фразы.
        """
        phrase = _clean_candidate(text)
        if not phrase:
            return None
        try:
            return self._parser.parse(phrase)
        except TimeParseError:
            when = self._parser.now + timedelta(
                minutes=DEFAULT_REMINDER_DELAY_MINUTES)
            return ReminderSpec(when=when, text=phrase)

    def add_event(self, spec: ReminderSpec) -> Optional[str]:
        """Создаёт событие-напоминание в Google Calendar через API.

        Возвращает id события или None при неудаче.
        """
        try:
            return self._google.create_reminder(
                summary=spec.text,
                when=spec.when,
            )
        except Exception as e:
            print(f"[Google] Ошибка создания напоминания: {e}")
            return None

    def auth_ready(self) -> bool:
        """Готовы ли авторизация и scope для Calendar."""
        return self._google.is_ready()
