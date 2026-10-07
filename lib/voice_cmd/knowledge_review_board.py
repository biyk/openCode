# lib/voice_cmd/knowledge_review_board.py
"""Операции доски знаний: снимок, движения корзин, статусы серверов.

Confirmed сливает match из commands.json (locked) + knowledge.json.
laya/undefined — только knowledge.json.

Правило удаления: ✕ на «Лайе» и «Подтверждено» только меняет статус (фраза
уезжает в «Не распознано»); настоящее удаление — единственное на этой странице.
"""

from __future__ import annotations

import json
import time
import urllib.request

from lib.core.errors import swallowed
from lib.voice_cmd.knowledge import (
    CONFIRMED, LAYA, UNDEFINED, KnowledgeStore, normalize_core, today_str,
)
from lib.voice_cmd.knowledge_learn import (  # noqa: F401
    atomic_dump_json, learn, learn_from_confirm, register_key)
from lib.voice_cmd.knowledge_review_unconfirm import (  # noqa: F401
    bucket_of, unconfirm_phrase)


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


def free_text_commands(commands_file: str) -> list[str]:
    """Id команд со свободным текстом ({{text}}) — им на доске дают селект ключа."""
    try:
        with open(commands_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        swallowed("review.free_text_commands", e)
        return []
    out: list[str] = []
    for cid, cmd in (data.get("commands") or {}).items():
        blob = cmd if isinstance(cmd, str) else " ".join(
            str(v) for v in cmd.values())
        if "{{text}}" in blob:
            out.append(cid)
    return sorted(out)


def locked_confirmed(commands_file: str) -> dict:
    """Уже работающие фразы вне knowledge.json: match-шаблоны (read-only)."""
    try:
        with open(commands_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        swallowed("review.locked_match", e)
        return {}
    today = today_str()
    out: dict[str, dict] = {}
    for cid, phrases in (data.get("match") or {}).items():
        for ph in phrases:
            out[normalize_core(ph)] = {"kind": "command", "command": cid,
                                       "hits": 0, "locked": True,
                                       "added": today,
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
            "freeText": free_text_commands(commands_file),
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


_TASKS_TTL = 300.0  # c — перечитать таблицу задач не чаще интервала
_tasks_cache: tuple[float, list[str]] = (0.0, [])


def sheet_task_titles() -> list[str]:
    """Названия задач real_life_tasks (кэш _TASKS_TTL, пустой не кэшируется)."""
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


def apply_act(store: KnowledgeStore, act: dict, commands_file: str = "") -> bool:
    """Операция доски: confirm/demote/forget/update/reset. True = успех.

    purge (✕ на «Подтверждено») не здесь: он отвечает серверу число снятых
    match-шаблонов, поэтому идёт мимо этой функции — unconfirm_phrase.
    """
    text, action = str(act.get("text") or ""), str(act.get("action") or "")
    if action == "confirm":
        ok = store.confirm(text)
        if ok and commands_file:
            learn_from_confirm(store, commands_file, text, act.get("key"))
        return ok
    if action == "demote":
        return store.demote(text)
    if action == "forget":
        # Настоящее удаление живёт только на «Не распознано». Сверху ✕ меняет
        # статус: confirmed/laya → undefined, а не стирает запись.
        bucket = bucket_of(store, text)
        if bucket is None:
            return False
        return store.forget(text) if bucket == UNDEFINED else store.demote(text)
    if action == "reset":
        # ✕ на «Лайе»: снять догадку ИИ, вернуть в undefined (не удалять).
        if bucket_of(store, text) != LAYA:
            return False
        return store.demote(text) and store.record(UNDEFINED, text)
    if action == "update":
        bucket = bucket_of(store, text) or LAYA
        kind = str(act.get("kind") or "command")
        cid = str(act.get("command") or "")
        event = act.get("event") or None
        key = str(act.get("key") or "")
        ok = store.record(bucket, text, kind=kind, command=cid or None,
                          event=event, key=key or None)
        # Confirmed-строку учим целиком: ключ команды И синоним задачи.
        # Только register_key терял синоним (ветка confirm ниже ловит лишь
        # переход laya/undefined→confirmed, а не «сохранить» на confirmed).
        if ok and bucket == CONFIRMED and commands_file:
            learn(store, commands_file, text=text, command=cid or None,
                  kind=kind, event=event, key=key)
        return ok
    return False
