"""Генератор таблицы соответствия команд и скиллов в COMMANDS.md."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from scripts.commands_md_data import load_json, read_skill_manifests  # noqa: E402
from scripts.commands_md_render import render_document, render_table  # noqa: E402

ROOT = SCRIPT_ROOT
DEFAULT_COMMANDS_PATH = ROOT / "targets" / "FLTP-5i3-16512" / "commands.json"
DEFAULT_SKILLS_DIR = ROOT / "cli" / ".opencode" / "skill"
DEFAULT_OUTPUT_PATH = ROOT / "COMMANDS.md"


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
