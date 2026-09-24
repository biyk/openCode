"""Работа с индексом git и .structure.json."""

import json
import subprocess
from pathlib import Path

from scripts.files_ignore import (
    IGNORED_DIRECTORIES,
    STRUCTURE_FILE,
    is_ignored_extension,
    is_ignored_filename,
)


def iter_project_files(root: Path):
    """Получает список отслеживаемых Git файлов."""

    process = subprocess.run(
        ["git", "ls-files", "-z", "--"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if process.returncode != 0:
        raise RuntimeError(
            process.stderr.decode("utf-8", errors="replace").strip()
            or "не удалось получить список файлов из git"
        )

    for encoded_path in process.stdout.split(b"\0"):
        if not encoded_path:
            continue

        relative_path = Path(
            encoded_path.decode("utf-8", errors="surrogateescape")
        )

        relative_posix = relative_path.as_posix()

        if relative_posix == STRUCTURE_FILE:
            continue

        if any(part in IGNORED_DIRECTORIES for part in relative_path.parts):
            continue

        if is_ignored_filename(relative_path):
            print(
                f"Пропуск файла с исключённым именем: "
                f"{relative_posix}"
            )
            continue

        if is_ignored_extension(relative_path):
            print(
                f"Пропуск файла с исключённым расширением: "
                f"{relative_posix}"
            )
            continue

        yield relative_path


def load_structure(path: Path) -> dict:
    """Загружает .structure.json.

    Если файла нет — возвращает пустой объект.
    """

    if not path.exists():
        return {}

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as error:
        raise RuntimeError(
            f"Не удалось прочитать {path}: {error}"
        ) from error

    if not isinstance(data, dict):
        raise RuntimeError(
            f"{path} должен содержать JSON-объект"
        )

    return data


def save_structure(path: Path, structure: dict):
    """Сохраняет .structure.json."""

    path.write_text(
        json.dumps(
            structure,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def read_file_content(path: Path) -> str:
    """Читает содержимое файла как UTF-8 текст.

    Для исходников, сохранённых с другой кодировкой,
    повреждённые байты заменяются символом �.
    """

    return path.read_bytes().decode(
        "utf-8",
        errors="replace",
    )
