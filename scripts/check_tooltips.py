# TOOLTIP: Проверяет наличие описания у файлов проекта в .structure.json
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

STRUCTURE_JSON_NAME = ".structure.json"

EXCLUDED_NAMES: set[str] = {
    ".gitignore",
    ".env",
    "credentials.json",
    "token.json",
    ".coverage",
    "htmlcov",
    "package-lock.json",
    "package.json",
    STRUCTURE_JSON_NAME,
}

EXCLUDED_DIRS: set[str] = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    ".idea",
    ".vscode",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
    "logs",
    "bin",
    "models",
    "temp",
}


def _is_excluded(path: str) -> bool:
    name = Path(path).name
    if name in EXCLUDED_NAMES:
        return True
    parts = Path(path).parts
    return any(part in EXCLUDED_DIRS for part in parts)


def _run_git(cmd: list[str]) -> list[str]:
    result = subprocess.run(cmd, capture_output=True, text=False)
    if result.returncode != 0:
        raise SystemExit(f"git failed: {result.stderr.decode()}")
    raw = result.stdout
    if not raw:
        return []
    return raw.decode("utf-8", errors="replace").rstrip("\0").split("\0")


def _git_files() -> list[str]:
    tracked = _run_git(["git", "ls-files", "-z"])
    untracked = _run_git(["git", "ls-files", "-z", "--others", "--exclude-standard"])
    return sorted(set(tracked + untracked))


def load_structure_json(root: Path) -> dict[str, str]:
    path = root / STRUCTURE_JSON_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: невалидный JSON: {exc}")
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: на верхнем уровне ожидается объект")
    return {str(k).strip("/"): str(v) for k, v in data.items()}


def _validate_files(files: list[str], root: Path, described: dict[str, str]) -> list[str]:
    errors: list[str] = []
    described_keys = set(described.keys())

    for f in sorted(files):
        if f not in described_keys:
            errors.append(f"{f}: нет записи в {STRUCTURE_JSON_NAME}")

    for key in described:
        if not (root / key).exists():
            missing = f"{key}: запись есть в {STRUCTURE_JSON_NAME},"
            missing += " но файл/папка не найден в репозитории"
            errors.append(missing)

    return errors


def validate(root: Path) -> list[str]:
    described = load_structure_json(root)
    files: list[str] = []
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if path.name == STRUCTURE_JSON_NAME:
            continue
        rel = path.relative_to(root).as_posix()
        if _is_excluded(rel):
            continue
        files.append(rel)
    return _validate_files(files, root, described)


def validate_git(root: Path) -> list[str]:
    described = load_structure_json(root)
    files = [f for f in _git_files() if not _is_excluded(f)]
    return _validate_files(files, root, described)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверка наличия описания у файлов в .structure.json",
    )
    parser.add_argument("--root", default=".", help="корень проекта")
    parser.add_argument(
        "--git",
        action="store_true",
        help="получить список файлов через git ls-files (tracked + untracked)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if args.git:
        errors = validate_git(root)
    else:
        errors = validate(root)

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
