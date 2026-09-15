"""Обработчик голосовых команд напоминаний.

Связывает распознанный текст («напомни мне через 3 часа постирать
бельё») с Google Calendar/Tasks через lib.google_calendar. Сначала
пробует детерминированный парсер времени (lib.time_parser), при неудаче
спрашивает LLM для извлечения времени и текста (с коротким таймаутом,
чтобы не блокировать голосовой цикл).
"""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

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

LLM_TIMEOUT_SECONDS = 20


def _clean_candidate(text: str) -> str:
    """Убирает триггерную часть и слова-заполнители из фразы.

    Триггер срезается по границе слова («напомним» целиком, а не
    первые 6 букв), чтобы не оставался хвост вроде «м …» после
    ошибочного распознавания Vosk.
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
    t = re.sub(r"^\s*(мне|пожалуйста|алиса)\s*", "", t)
    t = re.sub(r"\s+пожалуйста\s*$", "", t)
    return t.strip()


class ReminderHandler:
    """Определяет, является ли текст напоминанием, и создаёт его."""

    def __init__(
        self,
        google: Optional[GoogleCalendar] = None,
        parser: Optional[TimeParser] = None,
        llm: Any = None,
    ) -> None:
        self._google = google or GoogleCalendar()
        self._parser = parser or TimeParser()
        self._llm = llm

    def is_reminder(self, text: str) -> bool:
        """Начинается ли текст с триггерной фразы напоминания."""
        t = text.lower().strip()
        return any(t.startswith(p) for p in TRIGGER_PHRASES) or \
            bool(re.match(r"напомнишь\b", t))

    def create(self, text: str) -> Optional[ReminderSpec]:
        """Разбирает время и текст напоминания.

        Возвращает ReminderSpec или None, если время не распознано.
        """
        phrase = _clean_candidate(text)
        if not phrase:
            return None
        try:
            return self._parser.parse(phrase)
        except TimeParseError:
            return self._parse_with_llm(phrase)

    def add_to_calendar(self, spec: ReminderSpec) -> Optional[str]:
        """Создаёт задачу Tasks + событие Calendar через Google API.

        Возвращает id события или None при неудаче.
        """
        try:
            result = self._google.create_reminder(
                summary=spec.text,
                when=spec.when,
            )
            return result.get("event")
        except Exception as e:
            print(f"[Google] Ошибка создания напоминания: {e}")
            return None

    def _parse_with_llm(self, phrase: str) -> Optional[ReminderSpec]:
        """Пытается извлечь время и текст через LLM (с таймаутом).

        LLM отвечает JSON {"when": "ISO8601", "text": "..."}. Таймаут
        короткий — голосовой цикл ждать ответ OmniRouter 300с не может.
        При неудаче возвращает None (текст уйдёт в обычный диалог).
        """
        if self._llm is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        prompt = (
            "Ты — парсер голосовых напоминаний. Текущее время (UTC): "
            f"{now}\n"
            f"Фраза пользователя: «{phrase}»\n"
            "Ответь строго JSON без пояснений в формате:\n"
            "{\"when\": \"ISO8601 datetime (UTC)\", \"text\": \"краткий "
            "текст напоминания\"}\n"
            "Пример: пользователь «через 3 часа постирать бельё» → "
            "{\"when\": \"<now+3h UTC>\", \"text\": \"постирать бельё\"}"
        )
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self._llm.ask, prompt)
                raw = future.result(timeout=LLM_TIMEOUT_SECONDS)
        except (_TimeoutError, Exception):
            return None
        if not raw or not isinstance(raw, str):
            return None
        m = re.search(r"\{\"when\"\s*:\s*\"([^\"]+)\"", raw)
        if not m:
            return None
        try:
            when = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
            text = self._extract_text(raw)
            if not text:
                return None
        except ValueError:
            return None
        return ReminderSpec(when=when, text=text)

    def _extract_text(self, raw: str) -> str:
        """Достаёт field text из JSON-ответа LLM, если он есть."""
        m = re.search(r"\"text\"\s*:\s*\"([^\"]+)\"", raw)
        if not m:
            return ""
        return m.group(1).strip() or "Напоминание"
