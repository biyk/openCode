"""Общие хелперы для generate_structure.py."""

from pathlib import Path
from typing import Any

try:
    from check_tooltips import EXCLUDED_DIRS, EXCLUDED_NAMES
except ImportError:
    from scripts.check_tooltips import EXCLUDED_DIRS, EXCLUDED_NAMES

RUSSIAN_CHARS = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")


class StructureError(Exception):
    """Ошибка валидности структуры проекта."""


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


def collect_index(repo: Any) -> set[str]:
    """Собирает множество путей отслеживаемых файлов из индекса git."""
    import subprocess

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
