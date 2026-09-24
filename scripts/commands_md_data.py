"""Загрузка и чтение данных для COMMANDS.md."""

import json
import re
from pathlib import Path
from typing import Any

SKILL_BY_COMMAND = {
    "volumeup": "volumeup",
    "volumedown": "volumedown",
    "playpause": "playpause",
    "stop": "stop",
    "openyoutube": "openyoutube",
    "youtube_news": "youtube_news",
    "news": "youtube_news",
    "calendar-reminder": "calendar-reminder",
    "task-add": "task-add",
    "calendar-plans": "calendar-plans",
    "task-complete": "task-complete",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"ожидался объект JSON: {path}")
    return data


def parse_skill_manifest(path: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        return data

    match = re.search(r"^---\s*\n(.*?)\n---\s*$", text, re.DOTALL)
    if not match:
        return None

    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.strip().partition(":")
        if not separator or key not in {"name", "description"}:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        fields[key] = value

    return fields or None


def read_skill_manifests(skills_dir: Path) -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    if not skills_dir.exists():
        return manifests

    for path in sorted(list(skills_dir.glob("*.json")) + list(skills_dir.glob("*.md"))):
        data = parse_skill_manifest(path)
        if data and isinstance(data.get("name"), str) and data["name"]:
            manifests[data["name"]] = data

    return manifests


def normalize_phrases(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        return []

    phrases: list[str] = []
    for item in values:
        phrase = str(item).strip()
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    return phrases


def skill_for_command(command_id: str, skills: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    skill_id = SKILL_BY_COMMAND.get(command_id, command_id)
    return skills.get(skill_id)


def description_for(
    command_id: str,
    commands: dict[str, Any],
    descriptions: dict[str, Any],
    sequences: dict[str, Any],
    skills: dict[str, dict[str, Any]],
) -> str:
    sequence = sequences.get(command_id, {})
    if isinstance(sequence, dict) and sequence.get("description"):
        return str(sequence["description"])

    command = commands.get(command_id)
    if isinstance(command, dict) and command.get("description"):
        return str(command["description"])

    if descriptions.get(command_id):
        return str(descriptions[command_id])

    skill = skill_for_command(command_id, skills)
    if skill and skill.get("description"):
        return str(skill["description"])

    return ""


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")
