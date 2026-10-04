# lib/voice_cmd/knowledge_resolve.py
"""Разрешение «фраза → решение» по confirmed-корзине (миксин KnowledgeStore).

Точный lookup по нормализованному ядру фразы: в рантайме живёт только
confirmed; laya/undefined здесь не решают. Миксин читает self._data и
self.reload() хост-класса.
"""

from __future__ import annotations

from typing import Optional

from lib.voice_cmd.knowledge_common import (
    COMMAND, CONFIRMED, FINISH, START, normalize_core,
)


class KnowledgeResolveMixin:
    """resolve/resolve_text/resolve_event — точный поиск по confirmed."""

    _data: dict

    def resolve(self, text: str) -> Optional[str]:
        """Confirmed-команда → id (точ lookup по нормализованному ядру)."""
        return self.resolve_text(text)[0]

    def resolve_text(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Confirmed-команда → (id, event|None); (None, None) если не команда.

        event — curated-текст с доски (параметр {{text}}): если задан,
        рантайм подставляет его как есть, не перерезая фразу заново.
        """
        self.reload()
        entry = self._data[CONFIRMED].get(normalize_core(text))
        if entry and entry.get("kind", COMMAND) == COMMAND and entry.get("command"):
            return str(entry["command"]), entry.get("event")
        return None, None

    def resolve_event(self, text: str) -> Optional[tuple[str, str]]:
        """Confirmed-мероприятие → (action, event_title) либо None."""
        self.reload()
        entry = self._data[CONFIRMED].get(normalize_core(text))
        if entry and entry.get("kind") in (START, FINISH) and entry.get("event"):
            return entry["kind"], str(entry["event"])
        return None
