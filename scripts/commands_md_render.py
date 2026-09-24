"""Рендер таблицы для COMMANDS.md."""

import re
from typing import Any

from scripts.commands_md_data import (
    description_for,
    markdown_cell,
    normalize_phrases,
    skill_for_command,
)

TABLE_MARKER = "## Таблица соответствия"


def render_table(commands: dict[str, Any], skills: dict[str, dict[str, Any]]) -> str:
    commands_config = commands.get("commands", {})
    match = commands.get("match", {})
    descriptions = commands.get("descriptions", {})
    sequences = commands.get("sequences", {})

    if not isinstance(commands_config, dict):
        commands_config = {}
    if not isinstance(match, dict):
        match = {}
    if not isinstance(descriptions, dict):
        descriptions = {}
    if not isinstance(sequences, dict):
        sequences = {}

    command_ids: list[str] = []

    def add_id(command_id: str) -> None:
        if command_id not in command_ids:
            command_ids.append(command_id)

    for command_id in commands_config:
        add_id(command_id)
    for command_id in sequences:
        add_id(command_id)
    for command_id in descriptions:
        add_id(command_id)
    for command_id in skills:
        add_id(command_id)

    rows: list[str] = []
    for command_id in command_ids:
        keys = normalize_phrases(match.get(command_id))
        if not keys:
            skill = skill_for_command(command_id, skills)
            if skill:
                keys = normalize_phrases(skill.get("phrases"))
        if not keys:
            keys = ["—"]

        description = description_for(
            command_id,
            commands_config,
            descriptions,
            sequences,
            skills,
        ) or "—"
        rows.append(
            f"| `{markdown_cell(command_id)}` | "
            f"{markdown_cell(', '.join(keys))} | {markdown_cell(description)} |"
        )

    lines = [
        "## Таблица соответствия",
        "",
        "| Код | Ключи | Описание |",
        "|---|---|---|",
        *rows,
        "",
    ]
    return "\n".join(lines)


def table_end_offset(content: str, start: int) -> int:
    match = re.search(r"\n#{2,6}\s+", content[start + len(TABLE_MARKER):])
    return start + len(TABLE_MARKER) + match.start() if match else len(content)


def render_document(current: str, table: str) -> str:
    start = current.find(TABLE_MARKER)
    if start == -1:
        prefix = current.rstrip() + "\n\n" if current else ""
        return prefix + table

    end = table_end_offset(current, start)
    return current[:start] + table + current[end:]


def extract_table(content: str) -> str:
    start = content.find(TABLE_MARKER)
    if start == -1:
        return ""
    return content[start:table_end_offset(content, start)]
