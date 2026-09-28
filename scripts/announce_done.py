# TOOLTIP: Озвучивает «Разработка завершена» (вызывается из hook post-commit)
"""Озвучка завершения разработки: пользователь слышит конец работы вслух.

Вызывается из `.git/hooks/post-commit` (коммит — момент окончания разработки).
Текст берётся из `lib/core/tuning.py::TASK_DONE_TEXT`, но читается как файл,
без импорта пакета `lib`: хук не должен падать из-за зависимостей приложения.
Кириллица передаётся через `--b64:` (консоль Windows в cp1251 портит аргументы).
Любая ошибка озвучки не должна ломать коммит — всегда нулевой код возврата.
"""

import argparse
import base64
import io
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TUNING_PATH = os.path.join(REPO_ROOT, "lib", "core", "tuning.py")
DEFAULT_TEXT = "Разработка завершена"
TTS_TIMEOUT_S = 90.0


def done_text() -> str:
    """Значение TASK_DONE_TEXT из tuning.py (без импорта) либо дефолт."""
    try:
        with io.open(TUNING_PATH, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("TASK_DONE_TEXT"):
                    value = line.split("=", 1)[1].strip().strip("\"'")
                    if value:
                        return value
    except Exception:
        pass  # blind-ok: ниже отдаём дефолт
    return DEFAULT_TEXT


def speak(text: str) -> int:
    """Прокидывает текст в `python -m lib.tts`; код возврата не значим."""
    payload = "--b64:" + base64.b64encode(text.encode("utf-8")).decode("ascii")
    try:
        subprocess.run([sys.executable, "-m", "lib.tts", payload],
                       timeout=TTS_TIMEOUT_S, cwd=REPO_ROOT, check=False)
    except Exception:
        pass  # blind-ok: озвучка не должна ронять коммит
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Озвучка завершения работы")
    parser.add_argument("text", nargs="*", help="свой текст вместо TASK_DONE_TEXT")
    args = parser.parse_args(argv)
    text = " ".join(args.text).strip() or done_text()
    return speak(text)


if __name__ == "__main__":
    raise SystemExit(main())
