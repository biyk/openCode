"""Супервизор фоновой диагностики (вотчдог + повторы)."""

import os
import threading
import time
from typing import Callable, Optional

from lib import diagnose as _dg
from lib.logger import latest_logs, read_llm_history, tail_lines
from lib.opencode_cli import OpenCodeCliRunner
from lib.output import TranscriptionOutput
from lib.tts import TextToSpeech


class DiagnoseSupervisor:
    """Супервизор фоновой диагностики (вотчдог + повторы)."""

    def __init__(
        self,
        runner: Optional[OpenCodeCliRunner] = None,
        output: Optional[TranscriptionOutput] = None,
        tts: Optional[TextToSpeech] = None,
        repo_root: Optional[str] = None,
        logs_dir: Optional[str] = None,
        stale_limit: float = _dg.STALE_LIMIT_SEC,
        attempt_timeout: float = _dg.ATTEMPT_TIMEOUT_SEC,
        poll_interval: float = _dg.POLL_INTERVAL_SEC,
        max_attempts: int = _dg.MAX_ATTEMPTS,
        on_say: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._runner = runner
        self._output = output or TranscriptionOutput()
        self._tts = tts
        self._repo = repo_root or _dg.REPO_ROOT
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
        return os.path.join(self._repo, _dg.WORKFILE)

    def _collect(self) -> Optional[tuple[str, list[str], list[dict]]]:
        """Последний лог + хвост + сообщения чата. None — логов нет."""
        commands_log, llm_log = latest_logs(self._logs_dir)
        if commands_log is None:
            return None
        tail = tail_lines(commands_log, _dg.LOG_TAIL_LINES)
        messages = read_llm_history(llm_log, _dg.CHAT_HISTORY_LIMIT) \
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
            if _dg.is_stale(max(progress, start_wall), time.time(),
                            self._stale_limit):
                state["stale"] = True
                abort.set()
                return

    def _attempt(self, prompt: str) -> tuple[str, str]:
        """Одна попытка: (результат, хвост вывода тестов).

        Результат: 'ok' | 'stale' | 'fail'. WORKING.MD пропал —
        прогоняем тесты: зелёные — 'ok', красные — 'fail' с хвостом
        вывода для следующей попытки.
        """
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
            return "stale", ""
        if not answer or os.path.exists(self._workfile()):
            return "fail", ""
        self._output.print_info("[Diagnose] Агент завершил, запускаю тесты")
        passed, tail = _dg.run_tests(self._repo)
        if passed:
            return "ok", ""
        return "fail", tail

    def supervise(self, focus: str = "") -> int:
        """Полный цикл: lock уже занят вызывающим. Возвращает код."""
        if _dg.git_status_dirty(self._repo):
            self._say(_dg.MSG_DIRTY)
            return 4
        collected = self._collect()
        if collected is None:
            self._say(_dg.MSG_NO_LOGS)
            return 4
        log_path, tail, messages = collected
        self._say(_dg.MSG_START)
        extra = ""
        for attempt in range(1, self._max_attempts + 1):
            prompt = _dg.build_prompt(log_path, tail, messages, focus, extra)
            result, test_out = self._attempt(prompt)
            if result == "ok":
                self._say(_dg.MSG_DONE)
                return 0
            if attempt >= self._max_attempts:
                break
            if result == "stale":
                self._say(f"{_dg.MSG_STALE} (попытка {attempt})")
                extra = ""
            else:
                self._say(f"{_dg.MSG_TESTS_FAIL} (попытка {attempt})")
                extra = test_out
            try:
                _dg.rollback_changes(self._repo)
            except Exception as e:
                self._output.print_error(
                    f"[Diagnose] Откат не удался: {e}")
                break
        self._say(_dg.MSG_FAIL)
        return 1
