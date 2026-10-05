# lib/scheduling/time_parser_clock.py
"""Разбор «часа/минут» из речи: число может быть цифрой ИЛИ словом.

Числительные словами («двенадцать часов», «пять часов тридцать минут»)
раньше понимал только «через …»; в «завтра в …» время искалось одними
цифрами и проваливалось в дефолт 09:00. Здесь — общий разбор, который
используют и «завтра/сегодня», и «в N часов».
"""

import re
from typing import Optional

# Слова-числительные (общие для «через …» и «в … часов»).
_WORD_NUM = {
    "одну": 1, "один": 1, "одна": 1, "одного": 1,
    "два": 2, "две": 2, "двух": 2, "полтора": 2,
    "три": 3, "четыре": 4, "пять": 5, "шесть": 6,
    "семь": 7, "восемь": 8, "девять": 9,
    "десять": 10, "одиннадцать": 11, "двенадцать": 12,
    "четырнадцать": 14, "пятнадцать": 15,
    "двадцать": 20, "двадцать один": 21, "двадцать пять": 25,
    "тридцать": 30, "сорок": 40, "сорок пять": 45, "пятьдесят": 50,
}

# Длинные (составные) формы — первыми, чтобы «двадцать пять» не свернуть
# в «двадцать» + мусор.
_WORD_NUM_RE = re.compile(
    r"\b(" + "|".join(sorted(_WORD_NUM, key=len, reverse=True)) + r")\b")

# Сначала длинные единицы, чтобы «часов» не съесть как «час».
_HOUR_UNIT_RE = re.compile(r"(часов|часа|час|ч)\b")
_MIN_UNIT_RE = re.compile(r"(минуты|минут|минуту|мин)\b")


def _read_num(s: str) -> Optional[tuple[int, int]]:
    """Ведущее число — цифра или слово: (значение, длина съеденного)."""
    m = re.match(r"\d{1,2}\b", s)
    if m:
        return int(m.group()), m.end()
    m = _WORD_NUM_RE.match(s)
    if m:
        return _WORD_NUM[m.group(1)], m.end()
    return None


def _extract_clock(rest: str) -> Optional[tuple[int, int, str]]:
    """(часы, минуты, остаток) из «12:30» / «N часов» / «N часов M минут»,
    где N/M — цифра ИЛИ слово. None, если времени в начале нет."""
    body = re.sub(r"^\s*в\s+", "", rest)
    num = _read_num(body)
    if num:
        hh, n = num
        tail = body[n:].lstrip()
        hm = _HOUR_UNIT_RE.match(tail)
        if hm:
            tail = tail[hm.end():].lstrip()
            mm, minutes = 0, tail
            num2 = _read_num(tail)
            if num2:
                mt = _MIN_UNIT_RE.match(tail[num2[1]:].lstrip())
                if mt:
                    mm = num2[0]
                    minutes = tail[num2[1]:].lstrip()[mt.end():].lstrip()
            if hh <= 24 and mm < 60:
                return hh, mm, minutes
    m = re.search(r"(\d{1,2})[.:]\s?(\d{2})", rest)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if hh <= 24 and mm < 60:
            after = rest[:m.start()] + " " + rest[m.end():]
            return hh, mm, re.sub(r"^\s*в\s+", "", after).strip()
    return None
