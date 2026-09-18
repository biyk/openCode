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
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from lib.logger import latest_logs, read_llm_history, tail_lines
from lib.opencode_cli import REPO_ROOT, OpenCodeCliRunner
from lib.output import TranscriptionOutput
from lib.tts import TextToSpeech

DIAGNOSE_ID = "diagnose"
WORKFILE = "WORKING.MD"
LOCKFILE = "diagnose.lock"
LOG_TAIL_LINES = 60
CHAT_HISTORY_LIMIT = 10
STALE_LIMIT_SEC = 600.0
ATTEMPT_TIMEOUT_SEC = 1800.0
POLL_INTERVAL_SEC = 15.0
MAX_ATTEMPTS = 5

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
MSG_DONE = "Диагностика завершена"
MSG_FAIL = "Диагностика не завершена после всех попыток"
MSG_NO_LOGS = "Нет логов для диагностики"


def build_prompt(log_path: str, log_tail: list[str],
                 messages: list[dict], focus: str) -> str:
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
    ]
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


class DiagnoseSupervisor:
    """Супервизор фоновой диагностики (вотчдог + повторы)."""

    def __init__(
        self,
        runner: Optional[OpenCodeCliRunner] = None,
        output: Optional[TranscriptionOutput] = None,
        tts: Optional[TextToSpeech] = None,
        repo_root: Optional[str] = None,
        logs_dir: Optional[str] = None,
        stale_limit: float = STALE_LIMIT_SEC,
        attempt_timeout: float = ATTEMPT_TIMEOUT_SEC,
        poll_interval: float = POLL_INTERVAL_SEC,
        max_attempts: int = MAX_ATTEMPTS,
        on_say: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._runner = runner
        self._output = output or TranscriptionOutput()
        self._tts = tts
        self._repo = repo_root or REPO_ROOT
        self._logs_dir = logs_dir or os.path.join(self._repo, "logs")
        self._stale_limit = stale_limit
        self._attempt_timeout = attempt_timeout
        self._poll_interval = poll_interval
        self._max_attempts = max_attempts
        self._on_say = on_say

    def _say(self, message: str) -> None:
        """Озвучка статуса (консоль + голос, голос не роняет процесс)."""
        self._output.print_info(f"[Diagnose] {message}")
        if self._on_say is not None:
            self._on_say(message)
            return
        try:
            tts = self._tts or TextToSpeech()
            tts.speak_and_play(message)
        except Exception as e:
            self._output.print_error(f"[Diagnose] Озвучка не удалась: {e}")

    def _workfile(self) -> str:
        return os.path.join(self._repo, WORKFILE)

    def _collect(self) -> Optional[tuple[str, list[str], list[dict]]]:
        """Последний лог + хвост + сообщения чата. None — логов нет."""
        commands_log, llm_log = latest_logs(self._logs_dir)
        if commands_log is None:
            return None
        tail = tail_lines(commands_log, LOG_TAIL_LINES)
        messages = read_llm_history(llm_log, CHAT_HISTORY_LIMIT) \
            if llm_log else []
        return commands_log, tail, messages

    def _watchdog(self, abort: threading.Event,
                  state: dict, start_wall: float) -> None:
        """Следит за mtime WORKING.MD; простой — abort (прибить агента)."""
        while not abort.is_set():
            time.sleep(self._poll_interval)
            try:
                progress = os.path.getmtime(self._workfile())
            except OSError:
                progress = start_wall
            if is_stale(max(progress, start_wall), time.time(),
                        self._stale_limit):
                state["stale"] = True
                abort.set()
                return

    def _attempt(self, prompt: str) -> str:
        """Одна попытка: 'ok' | 'stale' | 'fail'."""
        try:
            os.unlink(self._workfile())
        except OSError:
            pass
        abort = threading.Event()
        state = {"stale": False}
        start_wall = time.time()
        watcher = threading.Thread(
            target=self._watchdog, args=(abort, state, start_wall),
            daemon=True)
        watcher.start()
        try:
            runner = self._runner or OpenCodeCliRunner()
            answer = runner.run(
                prompt, abort_event=abort, raw=True,
                timeout=self._attempt_timeout)
        finally:
            abort.set()
            watcher.join(timeout=5)
        if state["stale"]:
            return "stale"
        if answer and not os.path.exists(self._workfile()):
            return "ok"
        return "fail"

    def supervise(self, focus: str = "") -> int:
        """Полный цикл: lock уже занят вызывающим. Возвращает код."""
        if git_status_dirty(self._repo):
            self._say(MSG_DIRTY)
            return 4
        collected = self._collect()
        if collected is None:
            self._say(MSG_NO_LOGS)
            return 4
        log_path, tail, messages = collected
        prompt = build_prompt(log_path, tail, messages, focus)
        self._say(MSG_START)
        for attempt in range(1, self._max_attempts + 1):
            result = self._attempt(prompt)
            if result == "ok":
                self._say(MSG_DONE)
                return 0
            if attempt >= self._max_attempts:
                break
            self._say(f"{MSG_STALE} (попытка {attempt})")
            try:
                rollback_changes(self._repo)
            except Exception as e:
                self._output.print_error(
                    f"[Diagnose] Откат не удался: {e}")
                break
        self._say(MSG_FAIL)
        return 1


def launch_detached(text: str,
                    repo_root: Optional[str] = None) -> int:
    """Спавнит detached-процесс супервизора, мгновенно возвращается."""
    repo_root = repo_root or REPO_ROOT
    logs_dir = os.path.join(repo_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = os.path.join(logs_dir, f"diagnose_{stamp}.log")
    cmd = [sys.executable, "-m", "lib.diagnose", "run", text]
    kwargs: dict = {
        "cwd": repo_root,
        "stdin": subprocess.DEVNULL,
        "stdout": open(log_path, "ab"),
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)
    return 0


def main(argv: Optional[list] = None) -> int:
    """CLI: `python -m lib.diagnose launch [текст]` / `run [текст]`.

    launch — спавн detached-супервизора (для шаблона commands.json,
    мгновенный возврат). run — сам супервизор (не вызывать вручную).
    """
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] not in ("launch", "run"):
        print("usage: python -m lib.diagnose launch [текст] | run [текст]")
        return 2
    text = " ".join(args[1:]).strip()
    if args[0] == "launch":
        try:
            return launch_detached(text)
        except Exception as e:
            print(f"error: {e}")
            return 1
    if not acquire_lock():
        sup = DiagnoseSupervisor()
        sup._say(MSG_BUSY)
        return 4
    try:
        return DiagnoseSupervisor().supervise(text)
    finally:
        release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
