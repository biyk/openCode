# lib/voice_cmd/knowledge_review_board.py
"""Операции доски знаний: снимок, движения корзин, статусы серверов.

Снимок confirmed сливает источники: шаблоны "match" из commands.json
(работают в рантайме, на доске — только для чтения, locked=true) +
подтверждённые записи knowledge.json (source=«знания», редактируемые).
laya/undefined — только knowledge.json, их наполняет живой пайплайн
(перезапущенный воркер).
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Optional

from lib.core.errors import swallowed
from lib.voice_cmd.knowledge import (
    BUCKETS, CONFIRMED, LAYA, UNDEFINED, KnowledgeStore, normalize_core,
)


def commands_lists(commands_file: str) -> tuple[list[str], dict]:
    """(id команд и sequence, описания) из commands.json."""
    try:
        with open(commands_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        swallowed("review.commands_lists", e)
        return [], {}
    ids = list(data.get("commands", {}))
    ids += [i for i in data.get("sequences", {}) if i not in ids]
    return ids, dict(data.get("descriptions") or {})


def locked_confirmed(commands_file: str) -> dict:
    """Уже работающие фразы вне knowledge.json: match-шаблоны (read-only)."""
    try:
        with open(commands_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        swallowed("review.locked_match", e)
        return {}
    out: dict[str, dict] = {}
    for cid, phrases in (data.get("match") or {}).items():
        for ph in phrases:
            out[normalize_core(ph)] = {"kind": "command", "command": cid,
                                       "hits": 0, "locked": True,
                                       "source": "commands.json"}
    return out


def board_snapshot(store: KnowledgeStore, commands_file: str,
                   review: dict) -> dict:
    """Снимок доски: корзины (confirmed с locked-источниками), команды, порт."""
    kb = {k: {**v, "source": "знания"} for k, v in
          store.entries(CONFIRMED).items()}
    boards = {CONFIRMED: {**locked_confirmed(commands_file), **kb},
              LAYA: store.entries(LAYA), UNDEFINED: store.entries(UNDEFINED)}
    commands, descriptions = commands_lists(commands_file)
    return {"boards": boards, "commands": commands,
            "descriptions": descriptions,
            "settings": {"llm_url": review.get("llm_url"),
                         "llm_model": review.get("llm_model")},
            "port": review.get("port")}


def laya_status(commands_file: str) -> dict:
    """{"enabled":…, "url":…, "up":…} — состояние decision-сервера Laya."""
    try:
        with open(commands_file, encoding="utf-8") as f:
            cfg = (json.load(f) or {}).get("decision") or {}
    except Exception as e:
        swallowed("review.laya_status", e)
        return {"enabled": False, "url": "", "up": False}
    url = str(cfg.get("url") or "")
    up = False
    if url:
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/health",
                                        timeout=2) as r:
                up = r.status == 200
        except OSError:
            up = False  # сервер лежит — штатный результат пробы
    return {"enabled": bool(cfg.get("enabled")), "url": url, "up": up}


_TASKS_TTL = 300.0  # c — перечитать таблицу задач не чаще этого интервала
_tasks_cache: tuple[float, list[str]] = (0.0, [])


def sheet_task_titles() -> list[str]:
    """Названия задач real_life_tasks — подсказка для task-complete на доске.

    Чтение Sheets дорогое (снимок доски опрашивается часто), поэтому ответ
    кэшируется на _TASKS_TTL секунд; пустой список не кэшируется (попробуем
    ещё раз — возможно, таблица/ OAuth были временно недоступны).
    """
    global _tasks_cache
    now = time.time()
    if _tasks_cache[1] and now - _tasks_cache[0] < _TASKS_TTL:
        return list(_tasks_cache[1])
    try:
        from lib.taskflow.real_life_sheet import RealLifeSheet
        rows = RealLifeSheet().read_all_tasks()
    except Exception as e:
        swallowed("review.sheet_tasks", e)
        return []
    titles = list(dict.fromkeys(str(r.get("task_title") or "").strip()
                                for r in rows
                                if str(r.get("task_title") or "").strip()))
    if titles:
        _tasks_cache = (now, list(titles))
    return titles


def _bucket_of(store: KnowledgeStore, text: str) -> Optional[str]:
    for b in BUCKETS:
        if text in store.entries(b):
            return b
    return None


def delete_confirmed_phrase(store: KnowledgeStore, commands_file: str,
                            text: str) -> dict:
    """Чистит устаревшую confirmed-фразу из ОБОИХ хранилищ сразу.

    knowledge.json — forget по всем корзинам; commands.json — убираем шаблон
    из match[cid] (сверка по normalize_core), при опустошении снимаем cid.
    Прочие секции конфига (commands/sequences/descriptions/criteria) не трогаем.
    """
    core = normalize_core(text)
    removed = store.forget(core)
    try:
        with open(commands_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        swallowed("review.delete_phrase.read", e)
        return {"knowledge": removed, "match": 0}
    match = data.get("match") or {}
    removed_match = 0
    for cid in list(match):
        kept = [t for t in match[cid] if normalize_core(t) != core]
        if len(kept) != len(match[cid]):
            removed_match += len(match[cid]) - len(kept)
            if kept:
                match[cid] = kept
            else:
                del match[cid]
    if removed_match:
        data["match"] = match
        try:
            tmp = commands_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
                f.write("\n")
            os.replace(tmp, commands_file)
        except Exception as e:
            swallowed("review.delete_phrase.write", e)
    return {"knowledge": removed, "match": removed_match}


def apply_act(store: KnowledgeStore, act: dict) -> bool:
    """Операция доски: confirm/demote/forget/update/reset. True = успех."""
    text, action = str(act.get("text") or ""), str(act.get("action") or "")
    if action == "confirm":
        return store.confirm(text)
    if action == "demote":
        return store.demote(text)
    if action == "forget":
        return store.forget(text)
    if action == "reset":
        # ✕ на «Лайе»: снять догадку ИИ, вернуть в undefined (не удалять).
        if _bucket_of(store, text) != LAYA:
            return False
        return store.demote(text) and store.record(UNDEFINED, text)
    if action == "update":
        bucket = _bucket_of(store, text) or LAYA
        return store.record(bucket, text,
                            kind=str(act.get("kind") or "command"),
                            command=act.get("command") or None,
                            event=act.get("event") or None)
    return False
