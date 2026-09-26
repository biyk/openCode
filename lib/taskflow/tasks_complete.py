"""Завершение задач по названию (миксин обработчика)."""

from difflib import SequenceMatcher
from typing import Optional

from lib.taskflow.tasks_parse import (
    COMPLETE_TRIGGER_PHRASES,
    _canonicalize,
    _clean_candidate,
    _normalize,
)

# Порог нечёткого совпадения названий (difflib ratio). Ошибки Vosk
# превращают «подчинить лампочку в ванной» в «починить лампочку ванной»,
# ratio при этом ~0.94; ниже 0.7 — уже другая задача.
FUZZY_RATIO = 0.72


class TaskCompleteMixin:
    """Миксин TaskHandler: «заверши задачу …» с exact/substring/fuzzy."""

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
