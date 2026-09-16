"""Парсинг времени и текста напоминания из русской голосовой команды.

Поддерживаемые конструкции:
- «через N час/часов/минут/дней/сек»
- «через полчаса», «через час», «через полтора часа»
- «завтра в HH:MM», «сегодня в HH:MM», «послезавтра в HH:MM»
- «в HH:MM» (ближайшее время сегодня, если уже прошло — завтра)
- даты вида «N-го/числа в HH:MM» (сегодня/завтра в пределах 2 дней)
- числительные: 1 час, 30 минут, 1 часа, 5 минут
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

_DOW_RE = re.compile(
    r"(понедельник|вторник|сред[ау]|четверг|пятниц[ау]|суббот[ау]|"
    r"воскресень[ае]|пн|вт|ср|чт|пт|сб|вс)", re.IGNORECASE)

# Слова-числительные: «через десять минут», «через два часа».
_WORD_NUM = {
    "одну": 1, "один": 1, "одного": 1, "час": 1,
    "два": 2, "полтора": 2,
    "три": 3, "четыре": 4, "пять": 5, "шесть": 6,
    "семь": 7, "восемь": 8, "девять": 9,
    "десять": 10, "одиннадцать": 11, "двенадцать": 12,
    "пятнадцать": 15, "двадцать": 20, "двадцать один": 21,
    "двадцать пять": 25, "тридцать": 30, "сорок": 40,
    "сорок пять": 45, "пятьдесят": 50,
}

_WORD_NUM_RE = re.compile(
    r"\b(одну|один|одного|час|два|полтора|три|четыре|пять|шесть|семь|"
    r"восемь|девять|десять|одиннадцать|двенадцать|пятнадцать|"
    r"двадцать пять|двадцать один|двадцать|тридцать|сорок пять|сорок|"
    r"пятьдесят)\b")


@dataclass
class ReminderSpec:
    """Разобранное напоминание: когда + что."""
    when: datetime
    text: str


class TimeParseError(ValueError):
    """Не удалось разобрать время из текста."""


class TimeParser:
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

    # ---------- «через N ...» ----------

    def _parse_through(self, phrase: str) -> Optional[tuple[datetime, str]]:
        m = re.match(r"через\s+(.*)", phrase)
        if not m:
            return None
        rest = m.group(1).strip()

        hm_match = re.match(r"(\d{1,2})[:. ](\d{2})\s+(.*)", rest)
        if hm_match:
            hh, mm, tail = int(hm_match.group(1)), int(hm_match.group(2)), \
                hm_match.group(3)
            if hh <= 24 and mm < 60:
                base = self._now.replace(hour=hh, minute=mm, second=0,
                                         microsecond=0)
                return self._next_hm(base, tail)

        if rest.startswith("полчаса"):
            return self._now + timedelta(minutes=30), rest[len("полчаса"):]
        if rest.startswith("полтора часа"):
            return self._now + timedelta(minutes=90), rest[len("полтора часа"):]
        if rest.startswith("час"):
            return self._now + timedelta(hours=1), rest[len("час"):]
        if rest.startswith("часа"):
            return self._now + timedelta(hours=1), rest[len("часа"):]

        m_num = re.match(
            r"(\d+)\s*"
            r"(часов|часа|час|минут|минуты|минуту|дней|дня|день)\b(.*)",
            rest)
        if m_num:
            n = int(m_num.group(1))
            unit = m_num.group(2)
            tail = m_num.group(3)
            if unit.startswith("час"):
                delta = timedelta(hours=n)
            elif unit.startswith("мин"):
                delta = timedelta(minutes=n)
            else:
                delta = timedelta(days=n)
            return self._now + delta, tail

        # «через десять минут», «через два часа» — числительное словом.
        word = _WORD_NUM_RE.match(rest)
        if word:
            num = _WORD_NUM[word.group(1)]
            tail = rest[word.end():].strip()
            unit_m = re.match(r"(час|часов|часа|минут|минуты|минуту)\b(.*)",
                              tail)
            if unit_m:
                unit_w = unit_m.group(1)
                tail = unit_m.group(2).strip()
                if unit_w.startswith("час"):
                    delta = timedelta(hours=num)
                else:
                    delta = timedelta(minutes=num)
                return self._now + delta, tail
        return None

    # ---------- «завтра/сегодня в HH:MM» ----------

    def _parse_rel_day(self, phrase: str) -> Optional[tuple[datetime, str]]:
        m = re.match(r"(завтра|послезавтра|сегодня)(?:\s+(?:в\s+)?(.*))?$",
                     phrase)
        if not m:
            return None
        day_word, rest = m.group(1), (m.group(2) or "").strip()
        delta = {"сегодня": 0, "завтра": 1, "послезавтра": 2}[day_word]
        when = self._now + timedelta(days=delta)

        if rest:
            hm = re.search(r"(\d{1,2})[.:]\s?(\d{2})", rest)
            if hm:
                hh, mm = int(hm.group(1)), int(hm.group(2))
                when = when.replace(hour=hh, minute=mm, second=0, microsecond=0)
                rest = rest.replace(hm.group(0), "", 1).strip()
                rest = re.sub(r"^\s*в\s+", "", rest)
            else:
                hmm = re.match(
                    r"(?:в\s+)?(\d{1,2})\s+часа?\s+(\d{1,2})\s+минут\b(.*)",
                    rest)
                if hmm:
                    hh, mm = int(hmm.group(1)), int(hmm.group(2))
                    when = when.replace(hour=hh, minute=mm, second=0,
                                        microsecond=0)
                    rest = hmm.group(3).strip()
                else:
                    when = when.replace(hour=9, minute=0, second=0,
                                        microsecond=0)
        else:
            when = when.replace(hour=9, minute=0, second=0, microsecond=0)
        return when, rest

    def _parse_hm(self, phrase: str) -> Optional[tuple[datetime, str]]:
        m = re.match(r"(?:в\s+)?(\d{1,2})[:. ]?(\d{2})(.*)", phrase)
        if not m:
            return None
        hh, mm, tail = int(m.group(1)), int(m.group(2)), (m.group(3) or "")
        if hh > 24 or mm >= 60:
            return None
        base = self._now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return self._next_hm(base, tail)

    def _next_hm(self, base: datetime, tail: str) -> tuple[datetime, str]:
        if base <= self._now:
            base += timedelta(days=1)
        return base, tail

    def _parse_hour_word(self,
                         phrase: str) -> Optional[tuple[datetime, str]]:
        """«в N часа|часов» или «в N минут» — ближайшее время с округлением."""
        m = re.match(
            r"в\s+(\d{1,2})\s+час(?:а|ов|ах)?(?:.*)$", phrase)
        if m:
            hh = int(m.group(1))
            if hh > 24:
                return None
            when = self._now.replace(hour=hh, minute=0, second=0,
                                     microsecond=0)
            if when <= self._now:
                when += timedelta(days=1)
            rest = re.sub(r"^в\s+\d{1,2}\s+час(?:а|ов|ах)?", "", phrase)
            return when, rest.strip()
        m = re.match(r"в\s+(\d{1,2})\s+минут", phrase)
        if m:
            mm = int(m.group(1))
            when = self._now.replace(minute=(self._now.minute + mm) % 60,
                                     second=0, microsecond=0)
            rest = re.sub(r"^в\s+\d{1,2}\s+минут", "", phrase)
            return when, rest.strip()
        return None

    def _parse_dow(self, phrase: str) -> Optional[tuple[datetime, str]]:
        m = _DOW_RE.search(phrase)
        if not m:
            return None
        names = {
            "понедельник": 0, "вторник": 1, "среда": 2, "среду": 2,
            "четверг": 3, "пятница": 4, "пятницу": 4, "суббота": 5,
            "субботу": 5, "воскресенье": 6, "воскресенья": 6,
            "пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6,
        }
        word = m.group(1)
        target = names.get(word.lower())
        if target is None:
            return None
        days_ahead = (target - self._now.weekday() + 7) % 7
        when = self._now + timedelta(days=days_ahead)
        when = when.replace(hour=9, minute=0, second=0, microsecond=0)
        rest = phrase[m.start():len(m.group(1)) + m.start()]
        rest = phrase[:m.start()] + phrase[m.end():]
        rest = re.sub(r"^\s*в\s+", "", rest).strip()
        return when, rest

    @staticmethod
    def _clean_text(text: str) -> str:
        """Убирает лишние предлоги и пробелы из текста напоминания."""
        text = re.sub(r"^\s*(чтобы|о том чтобы|мне|про|по поводу)\s+", "", text)
        text = text.strip(" ,;:.!?")
        words = text.split()
        # Убираем хвостовые предлоги «о», «об», «про», «за», «на»
        while words and words[-1] in ("о", "об", "про", "за", "на", "в"):
            words.pop()
        return " ".join(words).strip() or "Напоминание"
