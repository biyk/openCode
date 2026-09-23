"""Команда «Анализ/Диагностика»: фоновая диагностика логов через opencode.

Голос: [Алиса] _анализ_ / _диагностика_ / _проверь логи_ / ...
Команда `diagnose` из commands.json: шаблон
`python -m lib.diagnose launch "{{text}}"` мгновенно возвращает
управление — `launch` спавнит detached-процесс супервизора (`run`),
поэтому голосовой цикл не блокируется на минуты работы агента.

Протокол агента (кладётся в текст задачи): создать WORKING.MD в корне
репозитория, отмечать в нём текущий статус, по завершении удалить
WORKING.MD за собой.

Супервизор: если WORKING.MD не правится дольше STALE_LIMIT_SEC —
принудительно завершить агента, откатить изменения (`git checkout --
.`), поставить задачу заново (до MAX_ATTEMPTS попыток).

Правило: грязный git-статус — только озвучка «сначала зафиксируй
изменения в гит», запуска нет.

Коды возврата CLI: 0 — ок/обработано, 1 — провал после повторов,
2 — неверные аргументы, 4 — предусловие не выполнено
(грязный гит / нет логов / уже идёт).
"""

import os
import subprocess
import sys
from typing import Optional

from lib.opencode_cli import REPO_ROOT

DIAGNOSE_ID = "diagnose"
WORKFILE = "WORKING.MD"
LOCKFILE = "diagnose.lock"
LOG_TAIL_LINES = 60
CHAT_HISTORY_LIMIT = 10
STALE_LIMIT_SEC = 600.0
ATTEMPT_TIMEOUT_SEC = 1800.0
POLL_INTERVAL_SEC = 15.0
MAX_ATTEMPTS = 5
TEST_TIMEOUT_SEC = 300
TEST_TAIL_LINES = 30

TRIGGER_PHRASES = (
    "анализ",
    "диагностика",
    "проверь логи",
    "проверь ошибки",
    "найди ошибки",
    "найди ошибку",
)

MSG_DIRTY = "Сначала зафиксируй изменения в гит, потом запускай диагностику"
MSG_BUSY = "Диагностика уже идёт"
MSG_START = "Начинаю диагностику. Слежу за прогрессом"
MSG_STALE = "Агент завис, откатываю изменения и запускаю заново"
MSG_TESTS_FAIL = "Тесты не прошли, откатываю изменения и запускаю заново"
MSG_DONE = "Диагностика завершена"
MSG_FAIL = "Диагностика не завершена после всех попыток"
MSG_NO_LOGS = "Нет логов для диагностики"


def build_prompt(log_path: str, log_tail: list[str],
                 messages: list[dict], focus: str,
                 extra: str = "") -> str:
    """Текст задачи агенту: лог + чат + протокол WORKING.MD."""
    lines = [
        "Ты — агент диагностики голосового ассистента.",
        f"Рабочая папка — корень репозитория: {REPO_ROOT}.",
        f"Путь к последнему логу: {log_path}",
        "Хвост лога:",
        *log_tail,
        "Последние сообщения чата:",
    ]
    for msg in messages:
        lines.append(f"[{msg['role']}] {msg['content']}")
    lines += [
        f"Фокус: {focus or 'всё'}.",
        "Задача: проанализируй лог и сообщения, найди ошибки "
        "и ИСПРАВЬ их в коде.",
        "Протокол: в начале создай файл WORKING.MD в корне репозитория "
        "и отмечай в нём текущий статус выполнения; после выполнения "
        "УДАЛИ за собой файл WORKING.MD.",
        "После удаления WORKING.MD будут запущены тесты "
        "(python -m pytest tests/ -q); если они не пройдут — изменения "
        "откатят и задача вернётся тебе заново.",
    ]
    if extra:
        lines += ["Результат прошлого запуска:", extra]
    return "\n".join(lines)


def git_status_dirty(repo_root: Optional[str] = None) -> bool:
    """Грязный ли git-статус (есть незафиксированные изменения)."""
    repo_root = repo_root or REPO_ROOT
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root, capture_output=True, text=True, timeout=30)
    except Exception:
        return True
    if proc.returncode != 0:
        return True
    return bool(proc.stdout.strip())


def is_stale(last_progress: float, now: float,
             limit: float = STALE_LIMIT_SEC) -> bool:
    """Простой ли прогресс дольше лимита (чистая функция для тестов)."""
    return (now - last_progress) > limit


def _pid_alive(pid: int) -> bool:
    """Жив ли процесс с pid (проверка существования)."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except Exception:
        return False
    return True


def acquire_lock(repo_root: Optional[str] = None) -> bool:
    """Занять lock-файл диагностики. False — уже идёт (живой pid)."""
    repo_root = repo_root or REPO_ROOT
    path = os.path.join(repo_root, "logs", LOCKFILE)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        return False
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                pid = int(f.read().strip())
        except (OSError, ValueError):
            pid = -1
        if pid > 0 and _pid_alive(pid):
            return False
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError:
        return False
    return True


def release_lock(repo_root: Optional[str] = None) -> None:
    """Снять lock-файл диагностики."""
    repo_root = repo_root or REPO_ROOT
    try:
        os.unlink(os.path.join(repo_root, "logs", LOCKFILE))
    except OSError:
        pass


def rollback_changes(repo_root: Optional[str] = None) -> None:
    """Откатить изменения tracked-файлов и удалить WORKING.MD."""
    repo_root = repo_root or REPO_ROOT
    subprocess.run(["git", "checkout", "--", "."],
                   cwd=repo_root, capture_output=True, timeout=120,
                   check=True)
    try:
        os.unlink(os.path.join(repo_root, WORKFILE))
    except OSError:
        pass


def run_tests(repo_root: Optional[str] = None) -> tuple[bool, str]:
    """Прогоняет pytest. Возвращает (прошли, хвост вывода)."""
    repo_root = repo_root or REPO_ROOT
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q"],
            cwd=repo_root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=TEST_TIMEOUT_SEC)
    except Exception as e:
        return False, f"запуск тестов не удался: {e}"
    out = (proc.stdout + proc.stderr).strip()
    tail = "\n".join(out.splitlines()[-TEST_TAIL_LINES:])
    return proc.returncode == 0, tail


if __name__ == "__main__":
    from lib.diagnose_cli import main
    raise SystemExit(main())
