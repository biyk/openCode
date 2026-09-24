"""Генератор STRUCTURE.md по плоскому манифесту описаний .structure.json.

Манифест — объект вида {"путь": "русское описание"} для файлов и каталогов.
Скрипт сравнивает описания с файлами из индекса git (tracked + untracked,
исключая EXCLUDED_NAMES/EXCLUDED_DIRS из check_tooltips) и рендерит дерево
проекта в STRUCTURE.md. Обязательны описания только файлов; для каталогов
фallback не требуется.

Режимы:
  --check   только проверить, что STRUCTURE.md актуален (0/1)
  --write   переписать STRUCTURE.md из манифеста (0)
  --stdout  напечатать сгенерированное дерево в stdout (0)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from scripts.structure_common import (  # noqa: E402
    StructureError,
    _is_excluded,
    collect_index,
    get_inferred_directories,
    validate_manifest,
)
from scripts.structure_render import render_document, render_structure  # noqa: E402


def build_structure(
    repo_path: Any,
    manifest_path: Any,
) -> str:
    """Строит содержимое STRUCTURE.md из манифеста."""
    manifest_file = Path(manifest_path)
    if not manifest_file.exists():
        raise StructureError(f"Манифест не найден: {manifest_path}")

    with manifest_file.open(encoding="utf-8") as file:
        manifest = json.load(file)
    if not isinstance(manifest, dict):
        raise StructureError(f"{manifest_path}: ожидается объект на верхнем уровне")

    files = {
        path for path in collect_index(repo_path)
        if not _is_excluded(path)
    }
    directories = get_inferred_directories(files)

    errors = validate_manifest(manifest, files, repo_path)
    if errors:
        raise StructureError("; ".join(errors))

    root = Path(repo_path).resolve().name
    return render_structure(root, manifest, files, directories)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Генерирует дерево проекта и русские описания в STRUCTURE.md."
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="только проверить актуальность")
    modes.add_argument("--write", action="store_true", help="обновить файл STRUCTURE.md")
    modes.add_argument("--stdout", action="store_true", help="печатает дерево в stdout")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(".structure.json"),
        help="путь к манифесту описаний",
    )
    parser.add_argument(
        "--structure",
        type=Path,
        default=Path("STRUCTURE.md"),
        help="путь к файлу структуры",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    args = _build_parser().parse_args(argv)
    structure_path = args.structure

    if args.stdout:
        tree = build_structure(structure_path.parent, args.manifest)
        sys.stdout.write(tree)
        return 0

    if not structure_path.exists():
        if args.check:
            print(f"Файл не найден: {structure_path}", file=sys.stderr)
            return 1
        structure_path.write_text("", encoding="utf-8")

    current = structure_path.read_text(encoding="utf-8")
    try:
        tree = build_structure(structure_path.parent, args.manifest)
    except StructureError as error:
        print(f"Ошибка валидности: {error}", file=sys.stderr)
        return 2

    expected = render_document(current, tree)
    if args.check:
        if current == expected:
            print("STRUCTURE.md актуален.")
            return 0
        print(
            "STRUCTURE.md устарел. Запустите: "
            "python scripts/generate_structure.py --write",
            file=sys.stderr,
        )
        return 1

    structure_path.write_text(expected, encoding="utf-8")
    print(f"Обновлён файл: {structure_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
