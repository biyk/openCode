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
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from check_tooltips import EXCLUDED_DIRS, EXCLUDED_NAMES
except ImportError:
    from scripts.check_tooltips import EXCLUDED_DIRS, EXCLUDED_NAMES


class StructureError(Exception):
    """Ошибка валидности структуры проекта."""


START_MARKER = "STRUCTURE:START"
END_MARKER = "STRUCTURE:END"
RUSSIAN_CHARS = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")


def _normalize_path(path: Any) -> str:
    value = str(path).replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value


def _is_excluded(path: str) -> bool:
    normalized = _normalize_path(path)
    name = Path(normalized).name
    if name in EXCLUDED_NAMES:
        return True
    parts = Path(normalized).parts
    return any(part in EXCLUDED_DIRS for part in parts)


def _has_russian_description(description: Any) -> bool:
    return isinstance(description, str) and any(
        char in RUSSIAN_CHARS for char in description
    )


def _description_for(
    descriptions: dict[str, Any],
    path: str,
) -> str:
    description = descriptions.get(path)
    if not _has_russian_description(description):
        return ""
    return str(description).strip()


def validate_manifest(
    manifest: dict[str, Any],
    expected_files: set[str],
    repo_path: Any,
) -> list[str]:
    """Валидирует плоский манифест описаний.

    Обязательно описание для каждого файла из индекса. Каталоги не обязаны
    иметь описание. В манифесте не должно быть неизвестных путей.

    Возвращает список ошибок (пустой, если всё ок).
    """
    repo = Path(repo_path)
    errors: list[str] = []

    for path in sorted(expected_files):
        normalized = _normalize_path(path)
        if normalized not in manifest:
            errors.append(f"описание отсутствует для файла: {normalized}")
        elif not _has_russian_description(manifest[normalized]):
            errors.append(f"описание для файла {normalized} не на русском языке")

    for path in sorted(manifest):
        normalized = _normalize_path(path)
        if not normalized:
            errors.append("пустой путь в манифесте")
            continue
        if _is_excluded(normalized):
            continue
        if not (repo / normalized).exists():
            errors.append(f"путь не найден на диске: {normalized}")

    return errors


def render_structure(
    root_name: str,
    manifest: dict[str, Any],
    files: set[str],
    directories: set[str],
) -> str:
    """Рендерит дерево проекта в строку Markdown."""
    files = {_normalize_path(path) for path in files}
    directories = {_normalize_path(path) for path in directories}
    root_name = root_name.replace("\\", "/").rstrip("/")

    children_dirs: dict[str, list[str]] = {}
    children_files: dict[str, list[str]] = {}
    for directory in directories:
        if directory == ".":
            continue
        parent = directory.rpartition("/")[0] or "."
        children_dirs.setdefault(parent, []).append(directory)
    for path in files:
        parent = path.rpartition("/")[0] or "."
        children_files.setdefault(parent, []).append(path)

    root_description = _description_for(manifest, ".")
    root_line = root_name + (f"  # {root_description}" if root_description else "")
    lines = [root_line]

    def append_entry(prefix: str, connector: str, path: str, is_directory: bool) -> None:
        name = path.rpartition("/")[2] if "/" in path else path
        label = f"{name}/" if is_directory else name
        description = _description_for(manifest, path)
        suffix = f"  # {description}" if description else ""
        lines.append(f"{prefix}{connector}{label}{suffix}")

    def walk(parent: str, prefix: str) -> None:
        entries = [(path, True) for path in sorted(children_dirs.get(parent, []))]
        entries += [(path, False) for path in sorted(children_files.get(parent, []))]
        for index, (path, is_directory) in enumerate(entries):
            is_last = index == len(entries) - 1
            connector = "└── " if is_last else "├── "
            append_entry(prefix, connector, path, is_directory)
            if is_directory:
                next_prefix = prefix + ("    " if is_last else "│   ")
                walk(path, next_prefix)

    walk(".", "")
    return "\n".join(lines)


def render_document(current: str, expected: str) -> str:
    """Заменяет сгенерированную область в текущем содержимом STRUCTURE.md."""
    start_marker = f"## {START_MARKER}"
    end_marker = f"## {END_MARKER}"
    region = f"{start_marker}\n```\n{expected.rstrip()}\n```\n{end_marker}"

    start_idx = current.find(start_marker)
    end_idx = current.find(end_marker)
    if start_idx != -1 and end_idx != -1:
        prefix = current[:start_idx].rstrip()
        suffix = current[end_idx + len(end_marker):]
        result = f"{prefix}\n\n{region}" if prefix else region
        if suffix.strip():
            result += "\n" + suffix.strip() + "\n"
        else:
            result += "\n"
        return result

    separator = "\n\n" if current.strip() else ""
    return current.rstrip() + separator + region + "\n"


def collect_index(repo: Any) -> set[str]:
    """Собирает множество путей отслеживаемых файлов из индекса git."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return set()
    return {
        path.replace("\\", "/")
        for path in result.stdout.split("\0")
        if path
    }


def get_inferred_directories(files: set[str]) -> set[str]:
    """Инференцирует множество путей каталогов из множества файлов."""
    directories: set[str] = set()
    for path in files:
        normalized = _normalize_path(path)
        parts = normalized.split("/")
        for index in range(1, len(parts)):
            directories.add("/".join(parts[:index]))
    directories.add(".")
    return directories


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
