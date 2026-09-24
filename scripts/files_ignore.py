"""Константы и хелперы фильтрации для list_files.py."""

from pathlib import Path

IGNORED_DIRECTORIES = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "models",
}

IGNORED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".pyc", ".pyo",
    ".mp3", ".mp4", ".avi", ".mov", ".wav",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".lock",
}

IGNORED_FILENAMES = {
    "VERSION",
}

STRUCTURE_FILE = ".structure.json"


def is_ignored_extension(path: Path) -> bool:
    return path.suffix.lower() in IGNORED_EXTENSIONS


def is_ignored_filename(path: Path) -> bool:
    return path.name in IGNORED_FILENAMES
