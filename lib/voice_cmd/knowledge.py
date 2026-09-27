# lib/voice_cmd/knowledge.py
"""База знаний: «фраза → решение» с корзинами статусов review-доски.

targets/<host>/knowledge.json: confirmed (решает в рантайме без LLM),
laya (распознано Лайей, ждёт досмотра), undefined (не распознано).
kind — «command» либо «start»/«finish» (мероприятие, поле event — заголовок).
Досмотр и перевод laya/undefined → confirmed делает человек.
"""

import json
import os
import threading
from typing import Optional

from lib.core.errors import swallowed

# Вид решения
COMMAND, START, FINISH = "command", "start", "finish"
# Статусы-корзины; подтверждённое решение не понижаем автозаписью,
# laya сильнее undefined.
CONFIRMED, LAYA, UNDEFINED = "confirmed", "laya", "undefined"
BUCKETS = (CONFIRMED, LAYA, UNDEFINED)
_RANK = {CONFIRMED: 3, LAYA: 2, UNDEFINED: 1}


def normalize_core(text: str) -> str:
    """Нормализация фразы: нижний регистр, ё→е, схлопывание пробелов."""
    return " ".join(text.lower().replace("ё", "е").split())


class KnowledgeStore:
    """Хранилище базы знаний с hot-reload (по mtime файла)."""

    def __init__(self, knowledge_file: Optional[str] = None) -> None:
        self._file = knowledge_file
        self._data: dict[str, dict] = {b: {} for b in BUCKETS}
        self._mtime = 0.0
        self._lock = threading.Lock()
        self._load()

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
        if not self._file:
            return
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for b in BUCKETS:
                self._data[b] = dict(raw.get(b) or {})
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

    def _save(self) -> None:
        if not self._file:
            return
        try:
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=4)
                f.write("\n")
            self._mtime = os.path.getmtime(self._file)
        except Exception as e:
            swallowed("knowledge.save", e)

    # ---- разрешение (в рантайме живёт только confirmed) ----
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

    # ---- автозапись из пайплайна ----
    def record(self, bucket: str, text: str, kind: str = COMMAND,
               command: Optional[str] = None, event: Optional[str] = None,
               ) -> bool:
        """Кладёт фразу в корзину, не понижая статус сильнее текущего."""
        core = normalize_core(text)
        if not core or bucket not in _RANK:
            return False
        with self._lock:
            current = self._bucket_of(core)
            if current is not None and _RANK[current] > _RANK[bucket]:
                return False
            hits = int((self._data.get(current or bucket, {})
                        .get(core, {}) or {}).get("hits", 0))
            entry: dict = {"kind": kind, "hits": hits}
            if command:
                entry["command"] = command
            if event:
                entry["event"] = event
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
