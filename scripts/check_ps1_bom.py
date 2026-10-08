# TOOLTIP: Проверяет, что каждый .ps1 с нелатинскими байтами имеет UTF-8 BOM
"""PS 5.1 на Windows читает .ps1 как cp1251, если BOM нет — ломает парсер
на кириллице. Реальный баг утреннего будильника 08:41/09:06:
`wake_video_and_volume.ps1` падал с `Missing closing '}'` именно поэтому
(и `SearchReplace` его молча терял после каждой правки).

Правило гейта:
  * если в файле есть байты > 0x7F — обязателен UTF-8 BOM (EF BB BF);
  * тело после BOM обязано декодироваться как UTF-8 (ловим mojibake);
  * чистые ASCII-скрипты могут жить без BOM — их PS читает без искажений.

CLI: `python scripts/check_ps1_bom.py [--root PATH] [--git]` —
0 если всё чисто, 1 + список проблем на stderr иначе (флаг --git берёт
трек+антрек через `git ls-files`, как check_lengths).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

UTF8_BOM = b"\xef\xbb\xbf"

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
    ".opencode",
    "build",
    "dist",
    "logs",
    "temp",
    "models",
    ".voice-cdp-profile-9222",
    "laya-lab",
}


def _is_excluded(relative: str) -> bool:
    parts = Path(relative).parts
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
    untracked = _run_git(
        ["git", "ls-files", "-z", "--others", "--exclude-standard"])
    return sorted(set(tracked + untracked))


def check_file(path: Path) -> list[str]:
    """Проблемы одного .ps1 — список строк; пусто = ОК."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        return [f"не читается: {exc}"]
    has_bom = data.startswith(UTF8_BOM)
    body = data[len(UTF8_BOM):] if has_bom else data
    has_non_ascii = any(byte > 0x7F for byte in body)
    problems: list[str] = []
    if has_non_ascii and not has_bom:
        problems.append(
            "нелатинские байты без UTF-8 BOM — PS 5.1 распарсит как cp1251")
    if has_bom:
        try:
            body.decode("utf-8")
        except UnicodeDecodeError as exc:
            problems.append(f"тело после BOM не декодируется UTF-8: {exc}")
    return problems


def _check_files(files: list[str], root: Path) -> list[str]:
    errors: list[str] = []
    for relative in files:
        if Path(relative).suffix.lower() != ".ps1":
            continue
        if _is_excluded(relative):
            continue
        path = root / relative
        if not path.exists():
            continue
        for problem in check_file(path):
            errors.append(f"{relative}: {problem}")
    return errors


def validate(root: Path) -> list[str]:
    """Обход всех .ps1 в root (кроме исключённых каталогов)."""
    files: list[str] = []
    for path in root.rglob("*.ps1"):
        rel = path.relative_to(root).as_posix()
        if _is_excluded(rel):
            continue
        files.append(rel)
    return _check_files(files, root)


def validate_git(root: Path) -> list[str]:
    """То же, но список файлов берём из git (tracked + untracked)."""
    return _check_files(_git_files(), root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверка UTF-8 BOM в .ps1 с нелатинскими символами",
    )
    parser.add_argument("--root", default=".", help="корень проекта")
    parser.add_argument(
        "--git",
        action="store_true",
        help="список файлов через git ls-files (tracked + untracked)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    errors = validate_git(root) if args.git else validate(root)
    if errors:
        print("PS 5.1 BOM gate: найдены проблемы", file=sys.stderr)
        for err in errors:
            print("  " + err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
