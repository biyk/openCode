# lib/voice_cmd/knowledge.py
"""База знаний: «фраза → решение» с корзинами статусов review-доски.

targets/<host>/knowledge.json: confirmed (решает в рантайме без LLM),
laya (распознано Лайей, ждёт досмотра), undefined (не распознано).
kind — «command» либо «start»/«finish» (мероприятие, поле event — заголовок).
Досмотр и перевод laya/undefined → confirmed делает человек.
Карта synonyms (рядом с корзинами): выученный с доски остаток фразы →
канонический заголовок задачи. Точный lookup confirmed — в ResolveMixin.
"""

import json
import os
import threading
from typing import Optional

from lib.core.errors import swallowed
from lib.voice_cmd.knowledge_common import (
    ADDED, BUCKETS, COMMAND, CONFIRMED, FINISH, LAYA, START, SYNONYMS,
    UNDEFINED, _RANK, normalize_core, today_str)
from lib.voice_cmd.knowledge_resolve import KnowledgeResolveMixin
from lib.voice_cmd.knowledge_synonyms import KnowledgeSynonymsMixin

__all__ = ["ADDED", "BUCKETS", "COMMAND", "CONFIRMED", "FINISH", "LAYA",
           "START", "SYNONYMS", "UNDEFINED", "normalize_core", "today_str",
           "KnowledgeStore"]


class KnowledgeStore(KnowledgeResolveMixin, KnowledgeSynonymsMixin):
    """Хранилище базы знаний с hot-reload (по mtime файла)."""

    def __init__(self, knowledge_file: Optional[str] = None) -> None:
        self._file = knowledge_file
        self._data: dict[str, dict] = {b: {} for b in BUCKETS}
        self._syn: dict[str, str] = {}
        self._mtime = 0.0
        self._lock = threading.Lock()
        self._load()
        # Апгрейд: ставим сегодняшнюю дату всем, у кого поля `added` ещё нет.
        with self._lock:
            if self._migrate_added():
                self._save()

    @staticmethod
    def path_for_commands_file(commands_file: str) -> str:
        """Путь к knowledge.json рядом с commands.json."""
        return os.path.join(os.path.dirname(commands_file), "knowledge.json")

    @property
    def enabled(self) -> bool:
        """Есть ли файл-хранилище (пустая база всё равно активна)."""
        return self._file is not None

    def _load(self) -> None:
        self._data = {b: {} for b in BUCKETS}
        self._syn = {}
        if not self._file:
            return
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for b in BUCKETS:
                self._data[b] = dict(raw.get(b) or {})
            self._syn = dict(raw.get(SYNONYMS) or {})
            self._mtime = os.path.getmtime(self._file)
        except FileNotFoundError:
            pass  # файла ещё нет (первая запись создаст его) — это не ошибка
        except Exception as e:
            swallowed("knowledge.load", e)

    def reload(self) -> None:
        """Перечитывает файл, если он изменился с прошлой загрузки."""
        if not self._file:
            return
        try:
            mtime = os.path.getmtime(self._file)
        except OSError:
            return
        if mtime == self._mtime:
            return
        with self._lock:
            self._load()
            # Внешний редактор мог дописать запись без `added` — чиним сразу.
            if self._migrate_added():
                self._save()

    def _migrate_added(self) -> bool:
        """Ставит сегодняшнюю дату записям без `added` (synonyms не трогаем). True — исправили."""
        today = today_str()
        changed = False
        for b in BUCKETS:
            for entry in self._data.get(b, {}).values():
                if isinstance(entry, dict) and not entry.get(ADDED):
                    entry[ADDED] = today
                    changed = True
        return changed

    def _save(self) -> None:
        if not self._file:
            return
        try:
            payload = {**self._data, SYNONYMS: self._syn}
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=4)
                f.write("\n")
            self._mtime = os.path.getmtime(self._file)
        except Exception as e:
            swallowed("knowledge.save", e)

    # ---- автозапись из пайплайна ----
    def record(self, bucket: str, text: str, kind: str = COMMAND,
               command: Optional[str] = None, event: Optional[str] = None,
               key: Optional[str] = None) -> bool:
        """Кладёт фразу в корзину; key — выбранный на доске триггер.

        `added` — дата первого появления записи: при перезаписи той же фразы
        сохраняем исходную, при новой — ставим сегодняшнюю.
        """
        core = normalize_core(text)
        if not core or bucket not in _RANK:
            return False
        with self._lock:
            current = self._bucket_of(core)
            if current is not None and _RANK[current] > _RANK[bucket]:
                return False
            prev = (self._data.get(current or bucket, {})
                    .get(core, {}) or {})
            hits = int(prev.get("hits", 0))
            added = str(prev.get(ADDED) or "") or today_str()
            raw: dict = {"kind": kind, "hits": hits, ADDED: added,
                         "command": command, "event": event, "key": key}
            entry: dict = {k: v for k, v in raw.items() if v is not None}
            for b in BUCKETS:
                self._data[b].pop(core, None)
            self._data[bucket][core] = entry
            self._save()
        return True

    def record_laya(self, text: str, command_id: str) -> bool:
        """Лайя распознала команду → корзина laya (ждёт подтверждения)."""
        return self.record(LAYA, text, COMMAND, command=command_id)

    def record_undefined(self, text: str) -> bool:
        """Ничего не распознано → корзина undefined."""
        return self.record(UNDEFINED, text)

    def _bucket_of(self, core: str) -> Optional[str]:
        for b in BUCKETS:
            if core in self._data[b]:
                return b
        return None

    # ---- операции доски ----
    def confirm(self, text: str) -> bool:
        """Переводит laya/undefined → confirmed. Возвращает True, если было."""
        return self._move(text, CONFIRMED)

    def demote(self, text: str) -> bool:
        """Снимает галочку: confirmed → undefined."""
        return self._move(text, UNDEFINED)

    def _move(self, text: str, bucket: str) -> bool:
        core = normalize_core(text)
        with self._lock:
            entry = None
            for b in BUCKETS:
                if b != bucket and core in self._data[b]:
                    entry = self._data[b].pop(core)
                    break
            if entry is None:
                return False
            self._data[bucket][core] = entry
            self._save()
        return True

    def forget(self, text: str) -> bool:
        """Удаляет фразу из всех корзин. True, если что-то было."""
        core = normalize_core(text)
        with self._lock:
            removed = any(self._data[b].pop(core, None) is not None
                          for b in BUCKETS)
            if removed:
                self._save()
            return removed

    def bump(self, text: str) -> None:
        """Увеличивает счётчик попаданий confirmed-записи."""
        core = normalize_core(text)
        with self._lock:
            entry = self._data[CONFIRMED].get(core)
            if entry is not None:
                entry["hits"] = int(entry.get("hits", 0)) + 1
                self._save()

    def entries(self, bucket: str) -> dict[str, dict]:
        """Копия корзины (для досмотра)."""
        self.reload()
        with self._lock:
            return {k: dict(v) for k, v in self._data.get(bucket, {}).items()}
