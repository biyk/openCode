"""База соответствий «коверканье → команда» (самообучение П6.0).

Хранится в targets/<host>/aliases.json:
{
  "aliases": {
    "включи и ютюб": {"command": "openyoutube", "hits": 3, "confirmed": true}
  },
  "pending": {
    "паузы": {"command": "playpause", "hits": 1, "confirmed": false}
  }
}

Проверяется после дословного матчинга, до intent-LLM: известное
коверканье запускает команду мгновенно, без вызова LLM. В резолве
участвуют только confirmed-записи; pending ждёт подтверждения
голосом («запомни»). Дословный шаблон commands.json всегда бьёт алиас.
"""

import json
import os
import threading
from typing import Optional


def normalize_core(text: str) -> str:
    """Нормализация фразы: нижний регистр, ё→е, схлопывание пробелов."""
    return " ".join(text.lower().replace("ё", "е").split())


class AliasStore:
    """Хранилище алиасов команд с hot-reload."""

    def __init__(self, aliases_file: Optional[str] = None) -> None:
        self._aliases_file = aliases_file
        self._aliases: dict[str, dict] = {}
        self._pending: dict[str, dict] = {}
        self._mtime = 0.0
        self._lock = threading.Lock()
        self._load()

    @staticmethod
    def path_for_commands_file(commands_file: str) -> str:
        """Возвращает путь к aliases.json рядом с commands.json."""
        return os.path.join(os.path.dirname(commands_file), "aliases.json")

    @property
    def enabled(self) -> bool:
        """Есть ли файл с алиасами."""
        return self._aliases_file is not None and bool(
            self._aliases or self._pending)

    def _load(self) -> None:
        """Читает файл алиасов."""
        self._aliases = {}
        self._pending = {}
        if not self._aliases_file:
            return
        try:
            with open(self._aliases_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._aliases = data.get("aliases", {})
            self._pending = data.get("pending", {})
            self._mtime = os.path.getmtime(self._aliases_file)
        except Exception:
            self._aliases = {}
            self._pending = {}

    def reload(self) -> None:
        """Перечитывает файл, если он изменился."""
        if not self._aliases_file:
            return
        try:
            mtime = os.path.getmtime(self._aliases_file)
        except OSError:
            return
        if mtime == self._mtime:
            return
        with self._lock:
            self._load()

    def _save(self) -> None:
        """Записывает текущее состояние в файл."""
        if not self._aliases_file:
            return
        data = {"aliases": self._aliases, "pending": self._pending}
        with open(self._aliases_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.write("\n")
        self._mtime = os.path.getmtime(self._aliases_file)

    def resolve(self, text: str) -> Optional[str]:
        """Возвращает id команды для confirmed-алиаса (или None)."""
        self.reload()
        core = normalize_core(text)
        with self._lock:
            entry = self._aliases.get(core)
        if entry and entry.get("confirmed") and entry.get("command"):
            return str(entry["command"])
        return None

    def bump(self, text: str) -> None:
        """Увеличивает счётчик срабатываний (статистика для П7)."""
        core = normalize_core(text)
        with self._lock:
            entry = self._aliases.get(core)
            if entry is None:
                return
            entry["hits"] = int(entry.get("hits", 0)) + 1
            self._save()

    def add(self, phrase: str, command_id: str,
            confirmed: bool = True) -> bool:
        """Добавляет алиас. Возвращает False при пустых аргументах."""
        core = normalize_core(phrase)
        command_id = command_id.strip()
        if not core or not command_id:
            return False
        with self._lock:
            if confirmed:
                self._pending.pop(core, None)
                self._aliases[core] = {
                    "command": command_id, "hits": 0, "confirmed": True,
                }
            else:
                if core not in self._aliases:
                    self._pending.setdefault(core, {
                        "command": command_id, "hits": 0, "confirmed": False,
                    })
            self._save()
        return True

    def confirm(self, phrase: str) -> Optional[str]:
        """Переносит pending-запись в алиасы. Возвращает id или None."""
        core = normalize_core(phrase)
        with self._lock:
            entry = self._pending.pop(core, None)
            if entry is None or not entry.get("command"):
                return None
            entry["confirmed"] = True
            self._aliases[core] = entry
            self._save()
            return str(entry["command"])

    def forget(self, phrase: str) -> bool:
        """Удаляет алиас/pending. Возвращает True, если что-то было."""
        core = normalize_core(phrase)
        with self._lock:
            removed = (self._aliases.pop(core, None) is not None
                       or self._pending.pop(core, None) is not None)
            if removed:
                self._save()
            return removed

    def pending_list(self) -> dict[str, dict]:
        """Копия pending-записей."""
        self.reload()
        with self._lock:
            return {k: dict(v) for k, v in self._pending.items()}

    def aliases_list(self) -> dict[str, dict]:
        """Копия confirmed-алиасов."""
        self.reload()
        with self._lock:
            return {k: dict(v) for k, v in self._aliases.items() if
                    v.get("confirmed")}
