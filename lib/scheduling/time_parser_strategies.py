"""Стратегии разбора времени для TimeParser (миксин)."""

import re
from datetime import datetime, timedelta
from typing import Optional

from lib.scheduling.time_parser_clock import (
    _WORD_NUM, _WORD_NUM_RE, _extract_clock,
)

_DOW_RE = re.compile(
    r"(понедельник|вторник|сред[ау]|четверг|пятниц[ау]|суббот[ау]|"
    r"воскресень[ае]|пн|вт|ср|чт|пт|сб|вс)", re.IGNORECASE)


class TimeParserStrategiesMixin:
    """Миксин TimeParser: «через», «завтра/в HH:MM», дни недели."""

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

    def _parse_rel_day(self, phrase: str) -> Optional[tuple[datetime, str]]:
        m = re.match(r"(завтра|послезавтра|сегодня)(?:\s+(?:в\s+)?(.*))?$",
                     phrase)
        if not m:
            return None
        day_word, rest = m.group(1), (m.group(2) or "").strip()
        delta = {"сегодня": 0, "завтра": 1, "послезавтра": 2}[day_word]
        when = self._now + timedelta(days=delta)
        # Час/минуты — цифрой ИЛИ словом («двенадцать часов»); времени нет —
        # дефолт 09:00. Раньше слово не распознавалось и падало в 9 утра.
        clock = _extract_clock(rest) if rest else None
        if clock:
            hh, mm, rest = clock
            when = when.replace(hour=hh, minute=mm, second=0, microsecond=0)
        else:
            when = when.replace(hour=9, minute=0, second=0, microsecond=0)
        rest = re.sub(r"^\s*в\s+", "", rest).strip()
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
        """«в N часа|часов» — ближайшее такое время; N — цифра или слово."""
        if not phrase.startswith("в "):
            return None
        clock = _extract_clock(phrase)
        if not clock:
            return None
        hh, mm, rest = clock
        when = self._now.replace(hour=hh, minute=mm, second=0,
                                 microsecond=0)
        if when <= self._now:
            when += timedelta(days=1)
        return when, rest.strip()

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
