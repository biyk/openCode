"""Планировщик по расписанию — локальный аналог cron.

Расписание — файл cron/crontab.json, задания — скрипты из cron/jobs/
(script) либо инлайн-команды (shell). Фоновый daemon-поток раз в секунду
проверяет расписание и запускает сработавшие задания; внутри одной минуты
задание выполняется один раз (дедупликация). Пропущенные из-за выключенного
ПК срабатывания не догоняются — как в обычном cron.

Скрипты заданий ищутся в каталоге jobs/ рядом с crontab.json; рабочая
директория (cwd) заданий — base_dir: каталог crontab.json по умолчанию,
либо корень репозитория, который передаёт main.py, чтобы скрипты могли
обращаться к файлам проекта относительно него (bin/, targets/, python -m
lib.*).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any, Callable, Optional

from lib.cron_jobs import CronJob, JobRunner
from lib.cron_parse import parse_cron

TICK_INTERVAL = 1.0


class CronScheduler:
    """Читает crontab.json и запускает задания по расписанию."""

    def __init__(self, crontab_file: Optional[str] = None,
                 output: Any = None, tts: Any = None,
                 now: Callable[[], datetime] = datetime.now,
                 base_dir: Optional[str] = None) -> None:
        self._path = crontab_file
        self._output = output
        self._now_fn = now
        if base_dir is None:
            base_dir = (os.path.dirname(crontab_file)
                        if crontab_file else os.getcwd())
        crontab_dir = (os.path.dirname(crontab_file)
                       if crontab_file else base_dir)
        jobs_dir = os.path.join(crontab_dir, "jobs")
        self._runner = JobRunner(base_dir, jobs_dir,
                                 output=output, tts=tts)
        self._mtime = 0.0
        self._jobs: list[CronJob] = []
        self._fired: dict[str, tuple[int, int, int, int, int]] = {}
        self._active: set[str] = set()
        self._active_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._load()

    # ---------- Загрузка расписания ----------

    def _load(self) -> None:
        self._jobs = []
        if not self._path:
            return
        try:
            with open(self._path, "r", encoding="utf-8") as file:
                data = json.load(file)
            self._mtime = os.path.getmtime(self._path)
        except (OSError, ValueError) as error:
            self._print(f"[cron] расписание не прочитано: {error}")
            return
        for item in data.get("jobs", []):
            try:
                self._jobs.append(self._parse_job(item))
            except ValueError as error:
                self._print(f"[cron] пропуск задания: {error}")

    def _parse_job(self, item: Any) -> CronJob:
        if not isinstance(item, dict):
            raise ValueError("задание не является объектом")
        job_id = str(item.get("id", "")).strip()
        if not job_id:
            raise ValueError("задание без id")
        schedule = str(item.get("schedule", "")).strip()
        expr = parse_cron(schedule)
        script = str(item.get("script", "")).strip()
        shell = str(item.get("shell", "")).strip()
        if script and shell:
            raise ValueError(f"«{job_id}»: заданы и script, и shell")
        if script:
            kind, command = "script", script
        elif shell:
            kind, command = "shell", shell
        else:
            raise ValueError(f"«{job_id}»: нет script/shell")
        enabled = bool(item.get("enabled", True))
        announce = bool(item.get("announce", False))
        try:
            timeout = float(item.get("timeout", 120.0))
        except (TypeError, ValueError):
            timeout = 120.0
        return CronJob(job_id, expr, kind, command, enabled, announce,
                       timeout)

    def reload(self) -> None:
        """Перечитывает расписание, если crontab.json изменился."""
        if not self._path:
            return
        try:
            mtime = os.path.getmtime(self._path)
        except OSError:
            return
        if mtime == self._mtime:
            return
        self._load()

    # ---------- Запуск / остановка потока ----------

    def start(self) -> None:
        """Запускает фоновый daemon-поток проверки расписания."""
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="cron-scheduler")
        self._thread.start()

    def stop(self) -> None:
        """Останавливает фоновый поток."""
        self._stop_event.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as error:
                self._print(f"[cron] ошибка цикла: {error}")
            self._stop_event.wait(TICK_INTERVAL)

    # ---------- Проверка и запуск заданий ----------

    def tick(self) -> None:
        """Проверяет расписание в текущий момент (публично для тестов)."""
        self.reload()
        if not self._jobs:
            return
        moment = self._now_fn()
        marker = (moment.year, moment.month, moment.day,
                  moment.hour, moment.minute)
        for job in self._jobs:
            if not job.enabled:
                continue
            if self._fired.get(job.job_id) == marker:
                continue
            if not job.expr.matches(moment):
                continue
            self._fired[job.job_id] = marker
            with self._active_lock:
                if job.job_id in self._active:
                    self._print(
                        f"[cron] «{job.job_id}» ещё выполняется, пропуск")
                    continue
                self._active.add(job.job_id)
            self._print(f"[cron] запуск задания «{job.job_id}»")
            threading.Thread(
                target=self._run_job, args=(job,), daemon=True).start()

    def _run_job(self, job: CronJob) -> None:
        try:
            self._runner.run(job)
        except Exception as error:
            self._print(f"[cron] «{job.job_id}»: ошибка: {error}")
        finally:
            with self._active_lock:
                self._active.discard(job.job_id)

    @property
    def jobs(self) -> list[CronJob]:
        """Текущий список заданий расписания."""
        return list(self._jobs)

    # ---------- Вывод ----------

    def _print(self, message: str) -> None:
        if self._output is not None:
            self._output.print_info(message)
        else:
            print(message)


__all__ = ["CronJob", "CronScheduler"]
