from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMMANDS_PATH = ROOT / "targets" / "FLTP-5i3-16512" / "commands.json"
DEFAULT_SKILLS_DIR = ROOT / "cli" / ".opencode" / "skill"
DEFAULT_OUTPUT_PATH = ROOT / "COMMANDS.md"
TABLE_MARKER = "## Таблица соответствия"

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

    for path in sorted(skills_dir.glob("*.json")):
        data = parse_skill_manifest(path)
        if data and isinstance(data.get("name"), str) and data["name"]:
            manifests[data["name"]] = data

    for path in sorted(skills_dir.glob("*.md")):
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Генерирует таблицу соответствия команд и скиллов в COMMANDS.md."
    )
    parser.add_argument("--commands", type=Path, default=DEFAULT_COMMANDS_PATH)
    parser.add_argument("--skills-dir", type=Path, default=DEFAULT_SKILLS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="только проверить актуальность")
    mode.add_argument("--write", action="store_true", help="обновить файл COMMANDS.md")
    mode.add_argument("--stdout", action="store_true", help="печатает таблицу в stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        commands = load_json(args.commands)
        skills = read_skill_manifests(args.skills_dir)
        table = render_table(commands, skills)

        if args.stdout:
            sys.stdout.write(table)
            return 0

        if not args.output.exists():
            if args.check:
                print(f"Файл не найден: {args.output}", file=sys.stderr)
                return 1
            args.output.write_text(render_document("", table), encoding="utf-8")
            print(f"Обновлён файл: {args.output}")
            return 0

        current = args.output.read_text(encoding="utf-8")
        expected = render_document(current, table)
        if args.check:
            if current == expected:
                print("COMMANDS.md актуален.")
                return 0

            print(
                "COMMANDS.md устарел. Запустите: "
                "python scripts/generate_commands_md.py --write",
                file=sys.stderr,
            )
            diff = "".join(
                difflib.unified_diff(
                    current.splitlines(True),
                    expected.splitlines(True),
                    fromfile=str(args.output),
                    tofile=str(args.output) + " (generated)",
                    lineterm="",
                )
            )
            sys.stderr.write(diff)
            return 1

        if current != expected:
            args.output.write_text(expected, encoding="utf-8")
            print(f"Обновлён файл: {args.output}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ошибка: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
