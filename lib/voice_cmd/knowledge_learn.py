# lib/voice_cmd/knowledge_learn.py
"""Обучение с доски: «✓ подтвердить» разлагает фразу на ключ команды и синоним.

Два разнесённых коллектора (как задумано изначально):
  • ключ команды  → commands.json["match"][cid] — рантайм ловит его на уровне 1
    (find_command), не доходя до LLM;
  • синоним задачи → knowledge.json["synonyms"] — остаток фразы после ключа
    кладётся на канонический заголовок, `_execute_decision` подставляет его.
Чистые функции, без сети: пишут в файлы так же атомарно, как purge.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from lib.core.errors import swallowed
from lib.voice_cmd.knowledge_common import (
    COMMAND, CONFIRMED, FINISH, START, normalize_core,
)

# Команды само-отчёта по задачам: параметр — название задачи (заголовок).
TASK_CMDS = ("taskstart", "taskdone")


def atomic_dump_json(path: str, data: dict, label: str = "json.dump") -> bool:
    """Атомарная запись JSON (tmp + os.replace, ensure_ascii=False, indent=4)."""
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.write("\n")
        os.replace(tmp, path)
        return True
    except Exception as e:
        swallowed(label, e)
        return False


def _fragment(text: str, key: str) -> str:
    """Остаток фразы после ключа: norm(text) минус norm(key)-префикс."""
    core = normalize_core(text)
    k = normalize_core(key)
    if k and core.startswith(k):
        core = normalize_core(core[len(k):])
    return core


def register_key(commands_file: str, cid: str, key: str) -> bool:
    """Добавляет key-фразу в match[cid] (дедуп по normalize_core). True = записал."""
    key = str(key or "").strip()
    if not cid or not key:
        return False
    try:
        with open(commands_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        swallowed("learn.read", e)
        return False
    match = data.get("match") or {}
    phrases = list(match.get(cid) or [])
    core = normalize_core(key)
    if any(normalize_core(p) == core for p in phrases):
        return False
    phrases.append(key)
    match[cid] = phrases
    data["match"] = match
    return atomic_dump_json(commands_file, data, "learn.write")


def _detect_key(text: str, command: str, commands_file: str) -> str:
    """Автоопределение ключа для task-команд: длиннейший префикс
    среди уже известных match[cid], иначе — первое слово.

    Релевантно только TASK_CMDS (taskdone/taskstart) — у них текст имеет
    структуру ГЛАГОЛ + фрагмент-задача. Для остальных команд ключ
    не угадывается (нужен ручной выбор)."""
    if command not in TASK_CMDS:
        return ""
    core = normalize_core(text)
    words = core.split(" ")
    if len(words) < 2:
        return ""
    # 1. Пробуем найти самый длинный префикс среди существующих match-фраз
    try:
        with open(commands_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        swallowed("learn.detect_key.read", e)
        data = {}
    phrases = (data.get("match") or {}).get(command) or []
    best = ""
    for ph in phrases:
        pn = normalize_core(ph)
        if core.startswith(pn) and len(pn) > len(best):
            best = pn
    if best:
        return best
    # 2. Иначе — первое слово (глагол), но не слишком короткое (местоимение "я")
    if len(words[0]) <= 2:
        return ""
    return words[0]


def learn(store, commands_file: str, *, text: str, command: Optional[str],
          kind: str, event: Optional[str], key: Optional[str]) -> bool:
    """Выучивает подтверждённую фразу; возвращает True, если что-то сохранил.

    command + key → match[command] (ключ-триггер команды); задача
    (command∈TASK_CMDS или kind∈{start,finish}) + event → синоним фрагмента.
    Не-задачные команды синоним не пишут — только ключ.
    """
    key = str(key or "").strip()
    if not key and command:
        key = _detect_key(text, command, commands_file)
    touched = False
    if command and key:
        touched = register_key(commands_file, command, key) or touched
    if (command in TASK_CMDS or kind in (START, FINISH)) and event:
        if command not in TASK_CMDS or key:
            touched = store.add_synonym(_fragment(text, key), event) or touched
    return touched


def learn_from_confirm(store, commands_file: str, text: str,
                       key: Optional[str]) -> bool:
    """Точка входа доски: берёт решение из confirmed-записи и учит по нему.

    Ключ: явный (из акта) иначе сохранённый на записи — тогда подтверждение
    галочкой не теряет ранее выбранный на доске ключ."""
    entry = store.entries(CONFIRMED).get(normalize_core(text), {})
    return learn(store, commands_file, text=text,
                 command=entry.get("command"), kind=entry.get("kind", COMMAND),
                 event=entry.get("event"), key=key or entry.get("key"))
