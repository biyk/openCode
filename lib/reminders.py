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

from lib.google_calendar import GoogleCalendar, GoogleOAuthError
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

    def authorize(self) -> None:
        """Обновляет доступ (refresh) или проходит интерактивный OAuth.

        Протухший access-токен молча обновляется по refresh_token;
        без токена/сколпов — открывается браузер для согласия.
        Бросает GoogleOAuthError, если авторизоваться не удалось.
        """
        self._google.authorize()


def main(argv=None) -> int:
    """CLI: `python -m lib.reminders "<фраза>"`.

    Разбирает фразу через ReminderHandler (время + текст; без времени —
    +60 минут), создаёт событие в Google Calendar и печатает отчёт.
    Используется командой calendar-reminder из commands.json.
    Коды: 0 — создано, 1 — ошибка API, 2 — нет фразы, 3 — пустая
    фраза или нет авторизации Calendar.
    """
    import sys

    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print('usage: python -m lib.reminders "<фраза>"')
        return 2
    handler = ReminderHandler()
    spec = handler.create(" ".join(args))
    if spec is None:
        print("Пустая фраза — нечего напоминать")
        return 3
    try:
        # Протухший токен обновляется здесь же (refresh); без
        # авторизации — интерактивный OAuth в браузере.
        handler.authorize()
    except GoogleOAuthError as e:
        print(f"[Google] Нет авторизации Calendar: {e}")
        return 3
    event_id = handler.add_event(spec)
    if not event_id:
        print("Не удалось создать напоминание")
        return 1
    print(f"reminder: {spec.text} @ {spec.when.isoformat()}")
    print(f"event_id: {event_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
