"""Выполнение заданий планировщика cron (script/shell) и озвучка итога.

Задание script — имя файла в каталоге cron/jobs/ рядом с crontab.json;
.ps1 запускается через powershell, остальные — через shell. Задание shell —
инлайн-команда через shell. Результат пишется в консоль/лог, при announce:
true озвучивается краткий итог через TTS.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Any

from lib.scheduling.cron_parse import CronExpr

DEFAULT_TIMEOUT = 120.0


def _tail(data: object, limit: int = 300) -> str:
    """Хвост вывода процесса как строка (для диагностики)."""
    if not isinstance(data, bytes):
        return ""
    text = data.decode("utf-8", errors="replace").strip()
    return text[-limit:]


@dataclass
class CronJob:
    """Одно задание расписания."""
    job_id: str
    expr: CronExpr
    kind: str  # "script" | "shell"
    command: str
    enabled: bool = True
    announce: bool = False
    timeout: float = DEFAULT_TIMEOUT


class JobRunner:
    """Запускает задание и сообщает итог в консоль/лог и через TTS."""

    def __init__(self, base_dir: str, jobs_dir: str,
                 output: Any = None, tts: Any = None) -> None:
        self._dir = base_dir
        self._jobs_dir = jobs_dir
        self._output = output
        self._tts = tts

    def run(self, job: CronJob) -> bool:
        """Выполняет задание; True при успехе, False при ошибке/неудаче."""
        try:
            ok = self.execute(job)
            self._print(f"[cron] «{job.job_id}»: "
                        + ("успех" if ok else "ошибка"))
            if job.announce:
                self._announce("задание выполнено" if ok
                               else "задание не выполнено")
            return ok
        except subprocess.TimeoutExpired as error:
            out = _tail(getattr(error, "stdout", None), 500)
            self._print(f"[cron] «{job.job_id}»: таймаут "
                        f"{job.timeout:.0f} с"
                        + (f", вывод: {out}" if out else ""))
            if job.announce:
                self._announce("задание не выполнено")
            return False
        except Exception as error:
            self._print(f"[cron] «{job.job_id}»: ошибка: {error}")
            if job.announce:
                self._announce("задание не выполнено")
            return False

    def execute(self, job: CronJob) -> bool:
        if job.kind == "script":
            script = self._script_path(job.command)
            if not os.path.isfile(script):
                self._print(f"[cron] скрипт не найден: {script}")
                return False
            if script.lower().endswith(".ps1"):
                command = ["powershell", "-NoProfile", "-ExecutionPolicy",
                           "Bypass", "-File", script]
                process = subprocess.run(
                    command, cwd=self._dir, capture_output=True,
                    timeout=job.timeout)
            else:
                process = subprocess.run(
                    script, shell=True, cwd=self._dir,
                    capture_output=True, timeout=job.timeout)
        else:
            process = subprocess.run(
                job.command, shell=True, cwd=self._dir,
                capture_output=True, timeout=job.timeout)
        # Вывод скрипта — единственная подсказка, где именно встал
        # шаг задания, поэтому пишем его в лог и при успехе тоже.
        out = _tail(process.stdout, 500)
        if out:
            self._print(f"[cron] «{job.job_id}» вывод: {out}")
        if process.returncode != 0:
            tail = _tail(process.stderr, 300)
            self._print(f"[cron] «{job.job_id}»: код "
                        f"{process.returncode}"
                        + (f", stderr: {tail}" if tail else ""))
            return False
        return True

    def _script_path(self, name: str) -> str:
        return os.path.join(self._jobs_dir, name)

    def _print(self, message: str) -> None:
        if self._output is not None:
            self._output.print_info(message)
        else:
            print(message)

    def _announce(self, message: str) -> None:
        tts = self._tts
        if tts is None:
            from lib.tts import TextToSpeech
            tts = TextToSpeech()
            self._tts = tts
        try:
            tts.speak_and_play(message)
        except Exception as error:
            self._print(f"[cron] озвучка не удалась: {error}")
