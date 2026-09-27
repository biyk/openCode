# lib/voice_cmd/knowledge_review_recognize.py
"""Распознавание фразы для доски «проверка знаний»: Laya → LLM (LM Studio).

try_recognize(text) сначала спрашивает Лайю (decision-секция commands.json),
затем LLM с полным набором команд; ответ — dict вида
{"via": "laya|llm|none", "kind": "command|start|finish|none",
 "command": id|"", "event": ""|заголовок}.

Настройки GUI-сервера (порт, адрес/модель LLM) лежат в
targets/<host>/review.json рядом с commands.json.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

import requests

from lib.core.errors import swallowed

DEFAULT_REVIEW = {
    "port": 8765,
    "llm_url": "http://localhost:1234/v1",
    "llm_model": "liquid/lfm2.5-1.2b",
    "llm_timeout": 300,
}
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
KINDS = ("command", "start", "finish", "none")

LLM_INSTRUCTIONS = (
    "Голосовая фраза пользователя (распознана с ошибками). "
    "Определи действие: верни СТРОГО JSON без пояснений вида "
    '{"kind":"command|start|finish|none","command":"<id из списка>",'
    '"event":"<заголовок мероприятия для start/finish, иначе пустая строка>"}. '
    "kind=command — просьба выполнить команду; start/finish — пользователь "
    "сам начал/завершил мероприятие; none — не команда."
)


def review_path(commands_file: str) -> str:
    """Путь к review.json рядом с commands.json."""
    return os.path.join(os.path.dirname(commands_file), "review.json")


def load_review(commands_file: str) -> dict:
    """Настройки доски: дефолты, перетёртые review.json."""
    data = dict(DEFAULT_REVIEW)
    try:
        with open(review_path(commands_file), encoding="utf-8") as f:
            data.update(json.load(f) or {})
    except FileNotFoundError:
        pass
    except Exception as e:
        swallowed("review.load", e)
    return data


def save_review(commands_file: str, data: dict) -> bool:
    """Пишет review.json (только известные ключи)."""
    keep = {k: data[k] for k in DEFAULT_REVIEW if k in data}
    try:
        with open(review_path(commands_file), "w", encoding="utf-8") as f:
            json.dump(keep, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        swallowed("review.save", e)
        return False


def _commands_meta(commands_file: str) -> tuple[list[str], dict]:
    """(id всех команд/sequence, decision-критерии) из commands.json."""
    try:
        with open(commands_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        swallowed("review.commands", e)
        return [], {}
    ids = list(data.get("commands", {}))
    ids += [i for i in data.get("sequences", {}) if i not in ids]
    criteria = dict((data.get("decision") or {}).get("criteria") or {})
    return ids, criteria


def laya_guess(text: str, commands_file: str) -> Optional[str]:
    """Ответ Лайи (id команды) либо None; сервер не автозапускаем."""
    try:
        with open(commands_file, encoding="utf-8") as f:
            cfg = (json.load(f) or {}).get("decision") or {}
    except Exception as e:
        swallowed("review.decision_cfg", e)
        return None
    if not cfg.get("enabled") or not cfg.get("url"):
        return None
    from lib.core.laya_decision import LayaDecision
    try:
        decision = LayaDecision(cfg)
    except ValueError:
        return None
    if not decision.available:
        return None
    hit = decision.detect(text)
    if hit and hit[0] != "none":
        return str(hit[0])
    return None


def _llm_question(text: str, criteria: dict) -> str:
    """Вопрос LLM: фраза + перечень команд (критерии Лайи, где есть)."""
    lines = [f"Фраза: {text}", "Команды (id — что делает):"]
    for cid, desc in criteria.items():
        if cid != "none":
            lines.append(f"- {cid} — {desc}")
    return "\n".join(lines)


def llm_guess(text: str, commands_file: str, review: dict
              ) -> Optional[dict]:
    """Спросить LLM (LM Studio, OpenAI-совместимый) и разобрать JSON-ответ."""
    ids, criteria = _commands_meta(commands_file)
    url = str(review.get("llm_url", "")).rstrip("/")
    if not url:
        return None
    payload = {
        "model": review.get("llm_model"),
        "messages": [
            {"role": "system", "content": LLM_INSTRUCTIONS},
            {"role": "user", "content": _llm_question(text, criteria)},
        ],
        "temperature": 0.0,
    }
    try:
        r = requests.post(f"{url}/chat/completions", json=payload,
                          timeout=float(review.get("llm_timeout", 300)))
        r.raise_for_status()
        answer = (r.json().get("choices") or [{}])[0].get(
            "message", {}).get("content") or ""
    except Exception as e:
        swallowed("review.llm", e)
        return None
    return _parse_llm(answer, ids)


def _parse_llm(answer: str, ids: list[str]) -> Optional[dict]:
    """Достаёт из ответа модели JSON и валидирует command/kind."""
    m = _JSON_RE.search(answer or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        swallowed("review.llm_json", e)
        return None
    kind = data.get("kind") if data.get("kind") in KINDS else "none"
    command = str(data.get("command") or "")
    if kind == "command" and command not in ids:
        return None
    if kind != "none" and kind != "command" and not data.get("event"):
        return None
    return {"kind": kind, "command": command if kind == "command" else "",
            "event": str(data.get("event") or "")}


def try_recognize(text: str, commands_file: str, review: dict) -> dict:
    """Полная попытка распознавания: сначала Лайя, затем LLM."""
    cid = laya_guess(text, commands_file)
    if cid:
        return {"via": "laya", "kind": "command", "command": cid,
                "event": ""}
    guess = llm_guess(text, commands_file, review)
    if guess:
        return {"via": "llm", **guess}
    return {"via": "none", "kind": "none", "command": "", "event": ""}
