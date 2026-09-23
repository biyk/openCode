"""Фолбэк-уровень: выполнение команды через консольный opencode (CLI).

Когда команда не совпала дословно с commands.json и mini-LLM не нашёл её,
текст уходит в консольный opencode, который запускается в папке cli/ и
подхватывает скиллы из cli/.opencode/skill/ (volumeup, task-add и
др.). Ответ агента печатается в лог; озвучку результата делает сам агент
через скилл speak-answer.
"""

import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Optional

from lib.opencode_output import OpenCodeOutputMixin, _strip_ansi
from lib.output import TranscriptionOutput

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI_DIR = os.path.join(REPO_ROOT, "cli")

DEFAULT_MODEL = "omnirouter/auto/tools"
DEFAULT_TIMEOUT = 120.0
BASE_PROMPT = (
    "от пользователя поступила команда: {text} - выполни. "
    "Если можешь выполнить команду скиллом или командой системы - сделай"
)


def _find_opencode_exe() -> Optional[str]:
    """Ищет исполняемый файл opencode (Windows: npm global .exe)."""
    found = shutil.which("opencode")
    if found and found.lower().endswith(".exe"):
        return found
    candidates = [
        os.path.join(
            os.environ.get("APPDATA", ""),
            "npm", "node_modules", "@opencode", "cli", "bin", "opencode.exe",
        ),
        os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Programs", "opencode", "opencode.exe",
        ),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


class OpenCodeCliRunner(OpenCodeOutputMixin):
    """Запускает console opencode в cli/ с текстом команды пользователя.

    В dev-режиме (raw=True) opencode запускается из корня проекта (REPO_ROOT)
    и получает текст пользователя напрямую, без BASE_PROMPT-обёртки.
    """

    def __init__(
        self,
        cli_dir: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        output: Optional[TranscriptionOutput] = None,
    ) -> None:
        self._cli_dir = cli_dir or CLI_DIR
        self._model = model
        self._timeout = timeout
        self._output = output or TranscriptionOutput()
        self._exe = _find_opencode_exe()

    def _build_command(self, prompt: str) -> list[str]:
        """Собирает argv для subprocess."""
        base = [self._exe] if self._exe else ["opencode"]
        return base + ["run", "--standalone", "--model", self._model, prompt]

    def run(self, text: str,
            abort_event: Optional[threading.Event] = None,
            raw: bool = False,
            verbose: Optional[bool] = None,
            timeout: Optional[float] = None) -> Optional[str]:
        """Выполняет команду через console opencode и возвращает текст ответа.

        raw=False: рабочий каталог cli/, текст оборачивается в BASE_PROMPT.
        raw=True (dev-режим): рабочий каталог корень проекта, текст передаётся
        модели без обёртки. verbose=True (по умолчанию = raw) — вывод CLI
        стримится в консоль построчно в реальном времени и итог возвращается
        без шумовой фильтрации, чтобы был виден сырой ответ и ошибки агента.
        timeout — лимит одной попытки в секундах (по умолчанию self._timeout;
        диагностике нужно больше).
        Возвращает None при провале запуска, таймауте или отмене (стоп).
        """
        if verbose is None:
            verbose = raw
        limit = timeout if timeout is not None else self._timeout
        text = (text or "").strip()
        if not text:
            return None
        run_dir = REPO_ROOT if raw else self._cli_dir
        if not os.path.isdir(run_dir):
            self._output.print_error(
                f"[OpenCode] Рабочая папка не найдена: {run_dir}")
            return None
        prompt = text if raw else BASE_PROMPT.format(text=text)
        cmd = self._build_command(prompt)
        self._output.print_info(
            f"[OpenCode] Запуск: opencode run --model {self._model} "
            f"(cwd: {run_dir}{', raw' if raw else ''})")

        kwargs = {
            "cwd": run_dir,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            proc = subprocess.Popen(cmd, **kwargs)
        except FileNotFoundError:
            self._output.print_error(
                "[OpenCode] opencode не найден в PATH. Установите CLI.")
            return None
        except Exception as e:
            self._output.print_error(f"[OpenCode] Ошибка запуска: {e}")
            return None

        chunks: list[str] = []
        stop = threading.Event()

        def _reader() -> None:
            try:
                while not stop.is_set():
                    line = proc.stdout.readline()
                    if not line:
                        break
                    chunks.append(line)
                    if verbose:
                        text_line = _strip_ansi(line).rstrip("\r\n")
                        if text_line.strip():
                            self._output.print_info(
                                f"[OpenCode>>] {text_line}")
            except Exception:
                pass

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()

        deadline = time.monotonic() + limit
        try:
            while True:
                if abort_event is not None and abort_event.is_set():
                    self._output.print_info("[OpenCode] Ответ отменён (стоп)")
                    return None
                if reader.is_alive() and proc.poll() is None:
                    if time.monotonic() >= deadline:
                        self._output.print_error(
                            f"[OpenCode] Таймаут {int(limit)}с")
                        self._dump_partial(chunks, verbose)
                        return None
                    time.sleep(0.2)
                    continue
                break
        finally:
            stop.set()
            if proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            reader.join(timeout=2)

        if abort_event is not None and abort_event.is_set():
            self._output.print_info("[OpenCode] Ответ отменён (стоп)")
            return None
        if verbose:
            # Dev-режим: без шумовой фильтрации, чтобы было видно,
            # что именно отвечает opencode и где ошибки.
            return _strip_ansi("".join(chunks)).strip() or None
        return self._clean("".join(chunks))
