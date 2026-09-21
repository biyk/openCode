import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

STRUCTURE_FILE = ".structure.json"

IGNORED_DIRECTORIES = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "models",
    "node_modules",
}

IGNORED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico",
    ".svg", ".webp",
    ".pdf",
    ".zip", ".tar", ".gz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".pyc", ".pyo",
    ".mp3", ".mp4", ".avi", ".mov", ".wav",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".lock",
}

IGNORED_FILENAMES = {
    "VERSION",
}


# Ищем TOOLTIP: и забираем всё после него до конца строки.
TOOLTIP_RE = re.compile(r"TOOLTIP:\s*(.*)")


def is_ignored(path: Path) -> bool:
    """Проверяет, нужно ли пропустить файл."""
    if path.name in IGNORED_FILENAMES:
        return True

    if path.suffix.lower() in IGNORED_EXTENSIONS:
        return True

    if any(part in IGNORED_DIRECTORIES for part in path.parts):
        return True

    return False


def iter_project_files():
    """Возвращает все файлы проекта, которые нужно проверить."""
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue

        relative_path = path.relative_to(ROOT)

        if relative_path.as_posix() == STRUCTURE_FILE:
            continue

        if is_ignored(relative_path):
            continue

        yield relative_path


def find_tooltip(path: Path) -> str | None:
    """
    Ищет первую строку, содержащую TOOLTIP:
    и возвращает всё, что находится после него.
    """

    try:
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError as e:
        print(f"ОШИБКА чтения {path}: {e}")
        return None

    for line in text.splitlines():
        match = TOOLTIP_RE.search(line)

        if match:
            tooltip = match.group(1).strip()

            if tooltip:
                return tooltip

    return None


def load_structure(path: Path) -> dict:
    """Загружает существующий .structure.json."""
    if not path.exists():
        return {}

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )

        if isinstance(data, dict):
            return data

        print(f"ВНИМАНИЕ: {path} содержит не JSON-объект.")
        return {}

    except (json.JSONDecodeError, OSError) as e:
        print(f"ОШИБКА чтения {path}: {e}")
        return {}


def save_structure(path: Path, structure: dict):
    """Сохраняет .structure.json."""
    path.write_text(
        json.dumps(
            structure,
            ensure_ascii=False,
            indent=4,
        ) + "\n",
        encoding="utf-8",
    )


def main():
    structure_path = ROOT / STRUCTURE_FILE

    # Загружаем существующие описания.
    structure = load_structure(structure_path)

    found = 0

    files = sorted(
        iter_project_files(),
        key=lambda p: p.as_posix().casefold(),
    )

    for relative_path in files:
        full_path = ROOT / relative_path

        tooltip = find_tooltip(full_path)

        if tooltip is None:
            continue

        key = relative_path.as_posix()

        structure[key] = tooltip
        found += 1

        print(f"{key} -> {tooltip}")

    save_structure(structure_path, structure)

    print()
    print(f"Найдено TOOLTIP: {found}")
    print(f"Записано в: {STRUCTURE_FILE}")
    print(f"Всего записей: {len(structure)}")


if __name__ == "__main__":
    main()
