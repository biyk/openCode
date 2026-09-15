#!/usr/bin/env python3
"""Повышает версию проекта (VERSION + lib/__init__.py) и коммитит.

Использование:
    python scripts/bump_version.py patch   # 1.0.0 → 1.0.1
    python scripts/bump_version.py minor   # 1.0.0 → 1.1.0
    python scripts/bump_version.py major   # 1.0.0 → 2.0.0

Не коммитит autonomously — это делает post-commit хук.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
INIT_FILE = ROOT / "lib" / "__init__.py"

_VERSION_RE = re.compile(r'^(\d+)\.(\d+)\.(\d+)$')
_INIT_RE = re.compile(r'^(__version__\s*=\s*")[^"]*(")$', re.MULTILINE)


def read_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def write_version(version: str) -> None:
    VERSION_FILE.write_text(version + "\n", encoding="utf-8")
    content = INIT_FILE.read_text(encoding="utf-8")
    new_content, n = _INIT_RE.subn(
        lambda m: f'{m.group(1)}{version}{m.group(2)}', content)
    if n != 1:
        raise RuntimeError(
            f"не удалось обновить __version__ в {INIT_FILE} ({n} замен)")
    INIT_FILE.write_text(new_content, encoding="utf-8")


def bump(current: str, kind: str) -> str:
    m = _VERSION_RE.match(current)
    if not m:
        raise RuntimeError(f"неверный формат версии: {current!r}")
    major, minor, patch = (int(x) for x in m.groups())
    if kind == "major":
        major, minor, patch = major + 1, 0, 0
    elif kind == "minor":
        minor, patch = minor + 1, 0
    elif kind == "patch":
        patch += 1
    else:
        raise RuntimeError(f"неизвестный тип: {kind!r}")
    return f"{major}.{minor}.{patch}"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    kind = sys.argv[1]
    if kind not in ("patch", "minor", "major"):
        print(f"неизвестный тип: {kind!r}", file=sys.stderr)
        return 1
    try:
        current = read_version()
        new = bump(current, kind)
        write_version(new)
        print(f"Версия: {current} -> {new}")
        return 0
    except Exception as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
