# TOOLTIP: Проверяет, что все файлы исходников короче MAX_LINES строк
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

MAX_LINES = 200

CODE_EXTENSIONS = {
    ".py",
    ".ps1",
    ".bat",
    ".cmd",
    ".sh",
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


def _is_code_file(name: str) -> bool:
    return Path(name).suffix.lower() in CODE_EXTENSIONS


def _is_excluded(path: str) -> bool:
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


def _count_lines(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    if not text:
        return 0
    return len(text.splitlines())


def _check_files(files: list[str], root: Path, limit: int) -> list[str]:
    errors: list[str] = []
    for relative in files:
        if not _is_code_file(relative) or _is_excluded(relative):
            continue
        path = root / relative
        if not path.exists():
            continue
        count = _count_lines(path)
        if count > limit:
            errors.append(f"{relative}: {count} строк (лимит {limit})")
    return errors


def validate(root: Path, limit: int = MAX_LINES) -> list[str]:
    files: list[str] = []
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        if _is_excluded(rel):
            continue
        files.append(rel)
    return _check_files(files, root, limit)


def validate_git(root: Path, limit: int = MAX_LINES) -> list[str]:
    files = _git_files()
    return _check_files(files, root, limit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверка, что файлы исходников не превышают лимит строк",
    )
    parser.add_argument("--root", default=".", help="корень проекта")
    parser.add_argument("--limit", type=int, default=MAX_LINES, help="лимит строк")
    parser.add_argument(
        "--git",
        action="store_true",
        help="получить список файлов через git ls-files (tracked + untracked)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if args.git:
        errors = validate_git(root, args.limit)
    else:
        errors = validate(root, args.limit)

    if errors:
        print(
            f"Найдено {len(errors)} файлов(а) длиннее {args.limit} строк:",
            file=sys.stderr,
        )
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
