"""Парсинг времени и текста напоминания из русской голосовой команды.

Поддерживаемые конструкции:
- «через N час/часов/минут/дней/сек»
- «через полчаса», «через час», «через полтора часа»
- «завтра в HH:MM», «сегодня в HH:MM», «послезавтра в HH:MM»
- «в HH:MM» (ближайшее время сегодня, если уже прошло — завтра)
- даты вида «N-го/числа в HH:MM» (сегодня/завтра в пределах 2 дней)
- числительные: 1 час, 30 минут, 1 часа, 5 минут
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from lib.time_parser_strategies import TimeParserStrategiesMixin


@dataclass
class ReminderSpec:
    """Разобранное напоминание: когда + что."""
    when: datetime
    text: str


class TimeParseError(ValueError):
    """Не удалось разобрать время из текста."""


class TimeParser(TimeParserStrategiesMixin):
    """Извлекает время (datetime) и текст напоминания из фразы.

    Фраза — то, что осталось после триггерных слов («напомни мне ...»).
    Если время не удалось распознать — поднимается TimeParseError.
    """

    def __init__(self, now: Optional[datetime] = None) -> None:
        """Парсер времени.

        `now` используется для тестов (фиксированное время); в реальном
        использовании он равен None, и тогда на каждый парсинг берётся
        живое `datetime.now()`, чтобы относительные команды («через 30
        минут») считались от момента команды, а не от старта приложения.
        """
        self._fixed_now = now

    @property
    def _now(self) -> datetime:
        """Актуальное «текущее» время для вычислений."""
        return self._fixed_now if self._fixed_now is not None else datetime.now()

    @property
    def now(self) -> datetime:
        """Текущее время, относительно которого парсится фраза."""
        return self._now

    def parse(self, phrase: str) -> ReminderSpec:
        """Возвращает напоминание с временем и оставшимся текстом."""
        phrase = phrase.strip().lower()
        if not phrase:
            raise TimeParseError("Пустая фраза")

        # «через N ...»
        through = self._parse_through(phrase)
        if through is not None:
            when, rest = through
            return ReminderSpec(when=when, text=self._clean_text(rest))

        # «завтра в HH:MM», «сегодня в HH:MM»
        rel_day = self._parse_rel_day(phrase)
        if rel_day is not None:
            when, rest = rel_day
            return ReminderSpec(when=when, text=self._clean_text(rest))

        # «в HH:MM» / «HH:MM»
        hm = self._parse_hm(phrase)
        if hm is not None:
            when, rest = hm
            return ReminderSpec(when=when, text=self._clean_text(rest))

        # «в N час(а)|N минут»
        hour_word = self._parse_hour_word(phrase)
        if hour_word is not None:
            when, rest = hour_word
            return ReminderSpec(when=when, text=self._clean_text(rest))

        # «в понедельник / пт ...»
        dow = self._parse_dow(phrase)
        if dow is not None:
            when, rest = dow
            return ReminderSpec(when=when, text=self._clean_text(rest))

        raise TimeParseError(f"Не понял время: «{phrase}»")
