"""Генератор STRUCTURE.md по манифесту описаний .structure.json.

Скрипт читает манифест описаний (файлы/каталоги + русские комментарии),
сравнивает его с индексом git (только staged-файлы) и рендерит дерево
проекта в STRUCTURE.md. Если в манифесте не хватает описания для какого-то
отслеживаемого файла или каталога — скрипт завершается с ошибкой, не
изменяя STRUCTURE.md.

Режимы:
  --check   только проверить, что STRUCTURE.md актуален (0/1)
  --write   переписать STRUCTURE.md из манифеста (0)
  --stdout  напечатать сгенерированное дерево в stdout (0)
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


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


def _is_excluded(path: str, exclusions: set[str]) -> bool:
    normalized = _normalize_path(path)
    for pattern in exclusions:
        normalized_pattern = _normalize_path(pattern)
        if fnmatch.fnmatchcase(normalized, normalized_pattern):
            return True
    return False


def _has_russian_description(description: Any) -> bool:
    return isinstance(description, str) and any(
        char in RUSSIAN_CHARS for char in description
    )


def _description_for(
    descriptions: dict[str, Any],
    path: str,
    fallback: str,
) -> str:
    description = descriptions.get(path)
    if not _has_russian_description(description):
        return fallback
    return str(description).strip()


def validate_manifest(
    manifest: dict[str, Any],
    expected_files: set[str],
    expected_directories: set[str],
    exclusions: set[str],
) -> list[str]:
    """Валидирует манифест описаний.

    Проверяет, что все ожидаемые файлы и каталоги имеют русское описание,
    что в манифесте нет неизвестных путей и что индекс не содержит
    исключённых путей.

    Возвращает список ошибок (пустой, если всё ок).
    """
    errors: list[str] = []
    files = manifest.get("files", {})
    directories = manifest.get("directories", {})

    if not isinstance(files, dict):
        errors.append("раздел files должен быть объектом")
        files = {}
    if not isinstance(directories, dict):
        errors.append("раздел directories должен быть объектом")
        directories = {}
    if not isinstance(exclusions, (list, set, tuple)):
        errors.append("раздел exclusions должен быть списком")
        exclusions = set()

    normalized_files = {
        _normalize_path(path): description
        for path, description in files.items()
    }
    normalized_directories = {
        _normalize_path(path): description
        for path, description in directories.items()
    }

    for path in sorted(expected_files):
        normalized = _normalize_path(path)
        if _is_excluded(normalized, exclusions):
            errors.append(f"путь исключён из структуры: {normalized}")
            continue
        if normalized not in normalized_files:
            errors.append(f"описание отсутствует для файла: {normalized}")
        elif not _has_russian_description(normalized_files[normalized]):
            errors.append(f"описание для файла {normalized} не на русском языке")

    for path in sorted(expected_directories):
        normalized = _normalize_path(path)
        if _is_excluded(normalized, exclusions):
            errors.append(f"путь исключён из структуры: {normalized}")
            continue
        if normalized not in normalized_directories:
            errors.append(f"описание отсутствует для каталога: {normalized}")
        elif not _has_russian_description(normalized_directories[normalized]):
            errors.append(f"описание для каталога {normalized} не на русском языке")

    for path in sorted(normalized_files):
        if not path:
            errors.append("пустой путь в манифесте")
            continue
        if _is_excluded(path, exclusions):
            errors.append(f"путь исключён из структуры: {path}")
            continue
        if path not in expected_files:
            errors.append(f"путь не найден в индексе: {path}")

    for path in sorted(normalized_directories):
        if not path:
            errors.append("пустой путь каталога в манифесте")
            continue
        if _is_excluded(path, exclusions):
            errors.append(f"путь исключён из структуры: {path}")
            continue
        if path not in expected_directories:
            errors.append(f"путь не найден в структуре: {path}")

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

    files_by_parent: dict[str, list[str]] = {}
    directories_by_parent: dict[str, list[str]] = {}
    for path in files:
        parent = path.rpartition("/")[0]
        files_by_parent.setdefault(parent, []).append(path)
    for path in directories:
        if path == ".":
            continue
        parent = path.rpartition("/")[0]
        directories_by_parent.setdefault(parent, []).append(path)

    for child_files in files_by_parent.values():
        child_files.sort()
    for child_directories in directories_by_parent.values():
        child_directories.sort()

    fallback_description = f"Описание каталога {root_name}"

    lines = [
        f"{root_name}/  # Описание: "
        f"{_description_for(manifest.get('directories', {}), '.', fallback_description)}."
    ]

    def render_node(path: str, prefix: str) -> None:
        children = directories_by_parent.get(path, []) + files_by_parent.get(path, [])
        children.sort(key=lambda item: (item not in directories_by_parent.get(path, []), item))
        for index, child in enumerate(children):
            is_last = index == len(children) - 1
            connector = "└── " if is_last else "├── "
            is_directory = child in directories_by_parent.get(path, [])
            child_path = f"{path}/{child}" if path != "." else child
            if is_directory:
                description = _description_for(
                    manifest.get("directories", {}),
                    child_path,
                    f"Описание каталога {child_path}",
                )
                lines.append(f"{prefix}{connector}{child}/  # Описание: {description}")
                next_prefix = prefix + ("    " if is_last else "│   ")
                if child in directories_by_parent.get(child_path, []) or any(
                    directory.startswith(f"{child_path}/")
                    for directory in directories
                ):
                    render_node(child_path, next_prefix)
            else:
                description = _description_for(
                    manifest.get("files", {}),
                    child_path,
                    f"Описание файла {child_path}",
                )
                lines.append(
                    f"{prefix}{connector}{child.split('/')[-1]}  # Описание: {description}"
                )

    root_children = (
        directories_by_parent.get(".", []) + files_by_parent.get(".", [])
    )
    root_children.sort(key=lambda item: (item not in directories_by_parent.get(".", []), item))
    for index, child in enumerate(root_children):
        is_last = index == len(root_children) - 1
        connector = "└── " if is_last else "├── "
        is_directory = child in directories_by_parent.get(".", [])
        child_path = child
        if is_directory:
            description = _description_for(
                manifest.get("directories", {}),
                child_path,
                f"Описание каталога {child_path}",
            )
            lines.append(f"{connector}{child}/  # Описание: {description}")
            next_prefix = "    " if is_last else "│   "
            if child in directories_by_parent.get(child_path, []):
                render_node(child_path, next_prefix)
        else:
            description = _description_for(
                manifest.get("files", {}),
                child_path,
                f"Описание файла {child_path}",
            )
            lines.append(
                f"{connector}{child.split('/')[-1]}  # Описание: {description}"
            )

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
        suffix = current[end_idx:]
        return f"{prefix}\n\n{region}\n{suffix}"

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
    tmp_path: Any,
    manifest_path: Any,
) -> str:
    """Строит содержимое STRUCTURE.md из манифеста."""
    manifest_file = Path(manifest_path)
    if not manifest_file.exists():
        raise StructureError(f"Манифест не найден: {manifest_path}")

    with manifest_file.open(encoding="utf-8") as file:
        manifest = json.load(file)

    exclusions = set(manifest.get("exclusions", set()))
    files = {
        path for path in collect_index(tmp_path)
        if not _is_excluded(path, exclusions)
    }
    directories = {
        path for path in get_inferred_directories(files)
        if not _is_excluded(path, exclusions)
    }

    errors = validate_manifest(manifest, files, directories, exclusions)
    if errors:
        raise StructureError("; ".join(errors))

    root = tmp_path.name if hasattr(tmp_path, "name") else "voice"
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
