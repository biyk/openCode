# lib/voice_cmd/knowledge_synonyms.py
"""Карта синонимов задачи: «остаток фразы → канонический заголовок» (миксин).

Выучивается с доски (`learn` в knowledge_learn) и используется `_execute_decision`
при подстановке параметра taskstart/taskdone. Хранится рядом с корзинами
в knowledge.json (`SYNONYMS` — top-level ключ), поэтому не затирается
автозаписью из пайплайна.

Миксин читает `self._syn`, `self._lock`, `self.reload()` и `self._save()`
хост-класса — ровно как KnowledgeResolveMixin читает `self._data`.
"""

from __future__ import annotations

from typing import Optional

from lib.voice_cmd.knowledge_common import normalize_core


class KnowledgeSynonymsMixin:
    """add_synonym / resolve_synonym / synonyms — карта «фрагмент → заголовок»."""

    _syn: dict

    def add_synonym(self, fragment: str, title: str) -> bool:
        """Кладёт «остаток фразы → канонический заголовок». True, если добавили."""
        core = normalize_core(fragment)
        if not core or not title or core == normalize_core(title):
            return False
        self.reload()
        with self._lock:                        # type: ignore[attr-defined]
            if self._syn.get(core) == title:
                return False
            self._syn[core] = title
            self._save()                        # type: ignore[attr-defined]
        return True

    def resolve_synonym(self, text: str) -> Optional[str]:
        """Задача-фрагмент → канонический заголовок (точ по norm-ядру)."""
        self.reload()
        return self._syn.get(normalize_core(text)) or None

    def synonyms(self) -> dict[str, str]:
        """Копия карты синонимов (для доски/отладки)."""
        self.reload()
        with self._lock:                        # type: ignore[attr-defined]
            return dict(self._syn)
