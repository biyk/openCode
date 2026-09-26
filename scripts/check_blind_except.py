# TOOLTIP: Проверяет, что новые except Exception не молчат (сверка с HEAD)
"""Стоп-кран для новых «слепых» except (TODO про скрытие ошибок).

`except Exception`/`except BaseException`/`except:` считается слепым, если
в теле блока нет следа обработки: print, логгера, raise, swallowed() или
явной метки `# blind-ok`. Проверка сравнивает число слепых блоков в
подготовленных (staged) .py-файлах с их версией в HEAD: рост числа — ошибка.
Старые нарушения поэтому легальны (baseline), а новые — нет.

Режимы:
  --git     staged-файлы против HEAD (используется в pre-commit)
  PATH...   проверить файлы/папки целиком (любой рост не нужен)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Заголовок слепого except: except Exception[ as e]: / except: / BaseException,
# в том числе с хвостовым комментарием (на нём и ставят метку # blind-ok).
BLIND_RE = re.compile(
    r"^\s*except\s*(?:\(?\s*(?:Exception|BaseException)\b[^)]*\)?\s*)?:(?:\s*#.*)?$"
)
# След обработки внутри тела блока.
EVIDENCE_RE = re.compile(
    r"print|_log|log_|logger|logging|raise|swallowed\(|blind-ok|print_"
)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def find_blind_excepts(text: str) -> list[tuple[int, str]]:
    """Слепые except-блоки без следа обработки: [(номер_строки, текст)]."""
    lines = text.splitlines()
    violations: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if not BLIND_RE.match(line):
            continue
        if EVIDENCE_RE.search(line):
            continue  # метка # blind-ok на самом except
        body: list[str] = []
        for j in range(i + 1, len(lines)):
            nxt = lines[j]
            if nxt.strip() and _indent(nxt) <= _indent(line):
                break
            body.append(nxt)
        if not any(EVIDENCE_RE.search(b) for b in body):
            violations.append((i + 1, line.strip()))
    return violations


def _run_git(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", errors="replace")


def _staged_py_files() -> list[str]:
    out = _run_git(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"])
    return [f for f in out.splitlines() if f.endswith(".py")]


def _staged_content(path: str) -> str:
    return _run_git(["git", "show", f":{path}"])


def _head_content(path: str) -> str:
    return _run_git(["git", "show", f"HEAD:{path}"])


def validate_git(root: Path) -> list[str]:
    """Ошибки для staged-файлов, где слепых except стало больше, чем в HEAD."""
    errors: list[str] = []
    for rel in _staged_py_files():
        path = root / rel
        if not path.exists():
            continue
        new_text = _staged_content(rel)
        old_count = len(find_blind_excepts(_head_content(rel)))
        violations = find_blind_excepts(new_text)
        if len(violations) > old_count:
            for line_no, text in violations:
                errors.append(f"{rel}:{line_no}: {text} (нет print/лог/raise)")
    return errors


def validate_paths(root: Path, paths: list[str]) -> list[str]:
    """Полная проверка файлов из paths (для ручного запуска)."""
    errors: list[str] = []
    for raw in paths:
        base = root / raw
        files = ([base] if base.is_file()
                 else sorted(base.rglob("*.py")))
        for path in files:
            if "__pycache__" in path.parts or "venv" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = path.relative_to(root).as_posix()
            for line_no, text_line in find_blind_excepts(text):
                errors.append(
                    f"{rel}:{line_no}: {text_line} (нет print/лог/raise)")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверка новых слепых except Exception (TODO blind-except)",
    )
    parser.add_argument("--root", default=".", help="корень проекта")
    parser.add_argument(
        "--git", action="store_true",
        help="сверить staged-.py с HEAD (режим pre-commit)",
    )
    parser.add_argument("paths", nargs="*", help="файлы/папки для полной проверки")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    errors = validate_git(root) if args.git else validate_paths(root, args.paths)

    if errors:
        print("Найдены «слепые» except (добавьте print/лог/raise/"
              "swallowed() или метку # blind-ok):", file=sys.stderr)
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
