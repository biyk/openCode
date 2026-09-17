"""Фолбэк-уровень: выполнение команды через консольный opencode (CLI).

Когда команда не совпала дословно с commands.json и mini-LLM не нашёл её,
текст уходит в консольный opencode, который запускается в папке cli/ и
подхватывает скиллы из cli/.opencode/skill/ (media-volume-up, task-add и
др.). Ответ агента печатается в лог; озвучку результата делает сам агент
через скилл speak-answer.
"""

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Optional

from lib.output import TranscriptionOutput

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI_DIR = os.path.join(REPO_ROOT, "cli")

DEFAULT_MODEL = "omnirouter/auto/tools"
DEFAULT_TIMEOUT = 120.0
BASE_PROMPT = (
    "от пользователя поступила команда: {text} - выполни. "
    "Если можешь выполнить команду скиллом или командой системы - сделай"
)
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# Открывающие блоки агента, которые режем целиком (до закрывающего тега)
_BLOCK_OPEN_RE = re.compile(r"^\s*<(parameter|system-reminder|function|supply)")


def _strip_ansi(text: str) -> str:
    """Убирает ANSI-управляющие последовательности из вывода."""
    return _ANSI_RE.sub("", text)


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


class OpenCodeCliRunner:
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
            verbose: Optional[bool] = None) -> Optional[str]:
        """Выполняет команду через console opencode и возвращает текст ответа.

        raw=False: рабочий каталог cli/, текст оборачивается в BASE_PROMPT.
        raw=True (dev-режим): рабочий каталог корень проекта, текст передаётся
        модели без обёртки. verbose=True (по умолчанию = raw) — вывод CLI
        стримится в консоль построчно в реальном времени и итог возвращается
        без шумовой фильтрации, чтобы был виден сырой ответ и ошибки агента.
        Возвращает None при провале запуска, таймауте или отмене (стоп).
        """
        if verbose is None:
            verbose = raw
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

        deadline = time.monotonic() + self._timeout
        try:
            while True:
                if abort_event is not None and abort_event.is_set():
                    self._output.print_info("[OpenCode] Ответ отменён (стоп)")
                    return None
                if reader.is_alive() and proc.poll() is None:
                    if time.monotonic() >= deadline:
                        self._output.print_error(
                            f"[OpenCode] Таймаут {int(self._timeout)}с")
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

    def _dump_partial(self, chunks: list[str], verbose: bool) -> None:
        """Показывает накопленный вывод CLI при таймауте (dev-режим)."""
        raw = _strip_ansi("".join(chunks))
        if not raw.strip():
            return
        if verbose:
            self._output.print_info(
                "[OpenCode] Вывод до таймаута:")
            for line in raw.splitlines():
                text_line = line.rstrip("\r\n")
                if text_line.strip():
                    self._output.print_info(f"[OpenCode>>] {text_line}")
        else:
            self._output.print_debug(
                f"[OpenCode] Вывод до таймаута:\n{raw}")

    def _clean(self, output: str) -> str:
        """Причёсывает вывод: ANSI, пустые подсказки, мусорные строки.

        Также отбрасывает технический шум агента: заголовки «> build»,
        спиннеры, вызовы несуществующих инструментов («No tool named ...»),
        JSON-параметры «<parameter=...>», «Arguments provided:». В итоге
        остаётся читаемый ответ, который и печатается в консоль.
        """
        raw = _strip_ansi(output)
        lines = []
        in_block = False
        for line in raw.splitlines():
            text = line.rstrip("\r\n")
            if not in_block and _BLOCK_OPEN_RE.match(text):
                # Выбрасываем весь блок агента до </...>
                in_block = True
                continue
            if in_block:
                if "</" in text or text.rstrip().endswith("/>"):
                    in_block = False
                continue
            if not self._is_noise_line(text):
                lines.append(text)
        # Схлопнуть повторные пустые строки
        cleaned = []
        for text in lines:
            if not text.strip() and cleaned and not cleaned[-1].strip():
                continue
            cleaned.append(text)
        return "\n".join(cleaned).strip() or None

    @staticmethod
    def _is_noise_line(text: str) -> bool:
        """Техническая ли шумовая строка вывода агента."""
        s = text.strip()
        if not s:
            return True
        low = s.lower()
        if low in (">", "thinking...", "accepting request for model update..."):
            return True
        if s.startswith("⠙") or s.startswith("⣾"):
            return True
        # Заголовки, стрелки, проваленные вызовы инструментов
        if s.startswith(">") or s.startswith("→") or s.startswith("✗"):
            return True
        # «$ cd C:\...; python -c ...» — исполняемые команды, не ответ
        if s.startswith("$"):
            return True
        # Ошибки агента про неизвестные инструменты/аргументы
        if "no tool named" in low or "invalid arguments for tool" in low:
            return True
        if "arguments provided" in low or "update the arguments" in low:
            return True
        if s == "{" or s == "}" or s == "}":
            return True
        # JSON-параметры («"filePath": "..."», «- path: Missing key»)
        if s.startswith('"') and ":" in s:
            return True
        if re.match(r"^-\s+\w+:", s):
            return True
        # Открытые блоки агента: <system-reminder>, <parameter=...>, <function>
        if s.startswith("<parameter") or s.startswith("<system-reminder") \
                or s.startswith("<function"):
            return True
        if s.startswith("</parameter") or s.startswith("</system-reminder") \
                or s.startswith("</function"):
            return True
        # Tool-call разметка агента, выведенная текстом (Anthropic/Claude):
        # <|tool| calls>, <|invoke ...>, <|parameter ...>, </|invoke>, </|calls>
        # — с обычным пайпом «|» или полной ширины «｜».
        if re.match(r"^</?[|｜][^>]*>", s):
            return True
        return False
