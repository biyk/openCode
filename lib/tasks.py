"""Обработчик голосовых команд задач («добавь задачу …», «заверши задачу …»).

Создание: связывает распознанный текст («добавь задачу: купить хлеб») с
Google Tasks через lib.google_tasks: текст без триггера становится
названием задачи в списке по умолчанию.

Завершение: «заверши задачу купить хлеб» загружает незавершённые задачи,
ищет по названию и отмечает совпадения выполненными.

Разбор детерминированный, LLM не используется.
"""

import base64
import json
import re
import sys
from difflib import SequenceMatcher
from typing import Optional

from lib.google_tasks import GoogleTasks

# Порог нечёткого совпадения названий (difflib ratio). Ошибки Vosk
# превращают «подчинить лампочку в ванной» в «починить лампочку ванной»,
# ratio при этом ~0.94; ниже 0.7 — уже другая задача.
FUZZY_RATIO = 0.72

TRIGGER_PHRASES = (
    "добавь задачу",
    "добавь задача",
    "создай задачу",
    "создай задача",
    "добавить задачу",
    "добавить задача",
    "создать задачу",
    "создать задача",
    "запиши задачу",
    "запиши задача",
    "запиши в задачи",
    "добавь в задачи",
    "новая задача",
)

COMPLETE_TRIGGER_PHRASES = (
    "заверши задачу",
    "завершить задачу",
    "выполни задачу",
    "выполнить задачу",
    "выполняй задачу",
    "выполняем задачу",
    "выполняю задачу",
    "выполнив задачу",
    "выполни задача",
    "выполнить задача",
    "отметь задачу выполненной",
    "отметь задачу как выполненную",
    "отметь выполненной задачу",
    "пометь задачу выполненной",
    "сделай задачу выполненной",
    "закрой задачу",
    "закрыть задачу",
    "закончи задачу",
)

_FILLERS_RE = re.compile(
    r"^\s*(?:(?:мне|пожалуйста|алиса|прошу)\s+)*"
    r"(?:мне|пожалуйста|алиса|прошу)?\s*")


def _canonicalize(text: str) -> str:
    """Убирает слова-заполнители в начале и между словами триггера.

    «добавь мне пожалуйста задачу убраться» → «добавь задачу убраться».
    """
    t = text.lower().strip()
    t = re.sub(r"\b(?:мне|пожалуйста|алиса|прошу)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _clean_candidate(text: str, phrases=TRIGGER_PHRASES) -> str:
    """Убирает триггерную часть и слова-заполнители из фразы.

    Триггер срезается по границе слова (как в lib.reminders), чтобы
    не оставался хвост после ошибочного распознавания Vosk.
    """
    t = _canonicalize(text)
    for phrase in phrases:
        if t.startswith(phrase):
            after = t[len(phrase):]
            if after and not after[0].isspace():
                continue
            t = after.strip()
            break
    t = _FILLERS_RE.sub("", t)
    t = re.sub(r"\s+пожалуйста\s*$", "", t)
    return t.strip()


class TaskHandler:
    """Определяет, является ли текст командой задачи, и создаёт/завершает её."""

    def __init__(
        self,
        google: Optional[GoogleTasks] = None,
    ) -> None:
        self._google = google or GoogleTasks()

    def is_task(self, text: str) -> bool:
        """Начинается ли текст с триггерной фразы задачи."""
        t = _canonicalize(text)
        return any(t.startswith(p) for p in TRIGGER_PHRASES)

    def create(self, text: str) -> Optional[str]:
        """Извлекает название задачи из фразы.

        Возвращает очищенный текст после триггера; None для пустой фразы.
        """
        return _clean_candidate(text) or None

    def add_task(self, title: str, notes: Optional[str] = None) -> Optional[str]:
        """Создаёт задачу в Google Tasks через API.

        Возвращает id задачи или None при неудаче.
        """
        try:
            return self._google.create_task(title=title, notes=notes)
        except Exception as e:
            print(f"[Google] Ошибка создания задачи: {e}")
            return None

    # ---------- Завершение ----------

    def is_complete_task(self, text: str) -> bool:
        """Начинается ли текст с триггерной фразы завершения задачи."""
        t = _canonicalize(text)
        return any(t.startswith(p) for p in COMPLETE_TRIGGER_PHRASES)

    def complete_parse(self, text: str) -> Optional[str]:
        """Извлекает название задачи из фразы завершения.

        Возвращает очищенный текст после триггера; None для пустой фразы.
        """
        return _clean_candidate(text, phrases=COMPLETE_TRIGGER_PHRASES) or None

    def complete_matching(self, title: str) -> dict:
        """Отмечает незавершённые задачи, подходящие по названию.

        Порядок совпадений: точное по нормализации; если нет — по
        вхождению подстроки; если и нет — нечёткое (difflib ratio >=
        FUZZY_RATIO, только лучший кандидат). Возвращает отчёт:
        {"matched": [...]}, каждый элемент —
        {"title", "id", "exact", "method"} (method: exact|substring|fuzzy).
        Некорректные названия/ошибки API возвращают пустой список.
        """
        if not title or not title.strip():
            return {"matched": []}
        query = _normalize(title)
        try:
            tasks = self._google.list_tasks(show_completed=False)
        except Exception as e:
            print(f"[Google] Ошибка загрузки задач: {e}")
            return {"matched": []}

        candidates = [t for t in tasks if t.get("title")]
        method = ""
        exact = [
            t for t in candidates
            if _normalize(t.get("title", "")) == query
        ]
        chosen = exact
        if chosen:
            method = "exact"
        if not chosen:
            chosen = [
                t for t in candidates if query in _normalize(t.get("title", ""))
            ]
            if chosen:
                method = "substring"
        if not chosen:
            # Только лучший нечёткий кандидат: fuzzy-совпадение может
            # случайно зацепить несколько задач, завершаем одну.
            best = None
            best_ratio = 0.0
            for t in candidates:
                ratio = SequenceMatcher(
                    None, query, _normalize(t.get("title", ""))
                ).ratio()
                if ratio > best_ratio:
                    best, best_ratio = t, ratio
            if best is not None and best_ratio >= FUZZY_RATIO:
                chosen = [best]
                method = "fuzzy"

        matched = []
        for task in chosen[:10]:
            try:
                updated = self._google.complete_task(str(task["id"]))
                if updated is None:
                    continue
            except Exception as e:
                print(f"[Google] Ошибка завершения задачи: {e}")
                continue
            matched.append({
                "title": task.get("title", ""),
                "id": str(task["id"]),
                "exact": method == "exact",
                "method": method,
            })
        return {"matched": matched}

    def auth_ready(self) -> bool:
        """Готовы ли авторизация и scope для Google Tasks."""
        return self._google.is_ready()


def _normalize(text: str) -> str:
    """Приводит название к единому виду для сравнения."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _decode_arg(raw: str) -> str:
    """Декодирует аргумент CLI: --b64:<base64> или обычный текст.

    base64 допускается (кириллица/кавычки в консоли), но НЕ обязателен:
    обычная фраза аргументом доходит как есть. Терпим к url-safe алфавиту
    (-_) и отсутствию паддинга.
    """
    raw = raw.strip()
    if raw.startswith("--b64:") or raw.startswith("--b64="):
        payload = raw.split(":", 1)[1] if ":" in raw[:6] else raw[6:]
        try:
            padded = payload.translate(str.maketrans("-_", "+/"))
            padded += "=" * (-len(padded) % 4)
            return base64.b64decode(padded).decode("utf-8")
        except Exception:
            return raw
    return raw


def main(argv: Optional[list] = None) -> int:
    """CLI: `python -m lib.tasks complete <фраза>` или `... --b64:<base64>`.

    Выполняет задачу по названию (complete_matching) и печатает отчёт в
    stdout. Используется скиллом task-complete в консольном opencode —
    единая короткая команда вместо фрагмента python -c внутри скилла.
    """
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m lib.tasks complete <фраза> | --b64:<base64>")
        return 2
    if args[0] != "complete":
        print(f"usage: python -m lib.tasks complete <фраза>; unknown: {args[0]}")
        return 2
    if len(args) < 2:
        print("usage: python -m lib.tasks complete <фраза>")
        return 2
    phrase = " ".join(_decode_arg(a) for a in args[1:])
    try:
        handler = TaskHandler()
        title = handler.complete_parse(phrase) or ""
        if not title:
            print("title: <пусто>")
            print("result: \"matched\": []")
            return 3
        result = handler.complete_matching(title)
        print("title:", title)
        print("result:", json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as e:
        print(f"error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
