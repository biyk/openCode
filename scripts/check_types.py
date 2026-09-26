# TOOLTIP: Запускает mypy по строгим зонам; не блокирует (сводка ошибок)
"""Неблокирующий прогон mypy (TODO про отсутствие проверки типов).

Конфиг — mypy.ini (зоны строгости). По умолчанию скрипт всегда возвращает 0:
он показывает, сколько типизации «в фоне», и не ломает работу/хуки. Флаг
--fail подключает код возврата mypy — с ним шаг можно будет добавить в
pre-commit, когда строгие зоны очистятся.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Зоны, где mypy должен быть близок к нулю ошибок.
STRICT_ZONES = ["lib/voice_cmd", "lib/core"]


def run_mypy(targets: list[str]) -> int:
    """Прогон `python -m mypy targets`; возвращает код возврата mypy."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "mypy", *targets],
            cwd=Path(__file__).resolve().parents[1])
    except OSError as exc:  # mypy не установлен
        print(f"mypy не запущен: {exc}", file=sys.stderr)
        return 0
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Неблокирующая проверка типов mypy по зонам (mypy.ini)",
    )
    parser.add_argument(
        "targets", nargs="*", default=None,
        help="что проверять (по умолчанию — строгие зоны из mypy.ini)",
    )
    parser.add_argument(
        "--fail", action="store_true",
        help="возвращать код mypy (для pre-commit, когда зоны очистятся)",
    )
    args = parser.parse_args(argv)

    targets = args.targets or STRICT_ZONES
    code = run_mypy(list(targets))
    if args.fail:
        return code
    if code != 0:
        print("[check_types] mypy находит ошибки — это пока не блокировка "
              "(см. TODO: включение типизации по зонам).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
