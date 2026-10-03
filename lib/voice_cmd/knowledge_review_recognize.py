# lib/voice_cmd/knowledge_review_recognize.py
"""Настройки доски «проверка знаний» и разбор ответов LLM (без сетевых ходов).

Здесь только то, что не обращается к ИИ: review.json (порт, адрес/модель,
таймаут), чтение commands.json (id команд, decision-критерии, match-шаблоны)
и разбор JSON-ответа модели с валидацией. Вопросы уровням —
knowledge_review_levels, порядок фаз и текстовый след прогона —
knowledge_review_detect.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

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
# Второй вопрос (фаза 2): команда уже известна, нужен только её параметр.
PARAM_INSTRUCTIONS = (
    "Фраза распознана с ошибками. Команда уже определена: {cmd}. "
    "Назови ТОЛЬКО объект, к которому она относится (что именно пользователь "
    "начал/закончил/включил и т.п.), парой слов в именительном падеже. "
    "Если объекта во фразе нет — верни NONE."
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


def commands_data(commands_file: str) -> dict:
    """Сырой commands.json ({} при сбое — доска не падает из-за конфига)."""
    try:
        with open(commands_file, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        swallowed("review.commands", e)
        return {}


def commands_meta(data: dict) -> tuple[list[str], dict]:
    """(id всех команд/sequence, decision-критерии) из прочитанного конфига."""
    ids = list(data.get("commands", {}))
    ids += [i for i in data.get("sequences", {}) if i not in ids]
    criteria = dict((data.get("decision") or {}).get("criteria") or {})
    return ids, criteria


def free_text_ids(data: dict) -> list[str]:
    """Id команд со свободным текстом ({{text}}) — у них параметр не задача."""
    out = []
    for cid, cmd in (data.get("commands") or {}).items():
        blob = cmd if isinstance(cmd, str) else " ".join(
            str(v) for v in cmd.values())
        if "{{text}}" in blob:
            out.append(cid)
    return out


def llm_question(text: str, criteria: dict) -> str:
    """Вопрос LLM: фраза + перечень команд (критерии Лайи, где есть)."""
    lines = [f"Фраза: {text}", "Команды (id — что делает):"]
    for cid, desc in criteria.items():
        if cid != "none":
            lines.append(f"- {cid} — {desc}")
    return "\n".join(lines)


def param_question(text: str, command: str, criteria: dict) -> str:
    """Вопрос LLM про параметр уже известной команды (фаза 2)."""
    what = criteria.get(command) or ""
    return "\n".join([
        PARAM_INSTRUCTIONS.format(cmd=f"{command} {what}".strip()),
        f"Фраза: {text}",
    ])


def parse_llm(answer: str, ids: list[str]) -> Optional[dict]:
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
