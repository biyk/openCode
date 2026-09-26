# TOOLTIP: Правка cron/crontab.json: сдвиг расписания задания по id (атомарная запись)
"""Правка расписания в cron/crontab.json (остальные поля заданий не трогаем).

Зачем: команда «я спать» переносит утреннее задание пробуждения на
«сейчас + 7ч30» (lib/sleep_event.py вызывает shift_job_schedule).
Запись атомарная (temp + os.replace), поэтому параллельный поток
планировщика никогда не увидит оборванный json.

Фоновый поток CronScheduler раз в секунду сравнивает mtime crontab.json
и перечитывает его (reload), так что правка файла подхватывается
запущенным процессом без перезапуска.

CLI для ручной проверки:
    python -m lib.scheduling.cron_edit <job_id> <hours> <minutes>
— сдвигает расписание задания на сейчас + hoursч minutesм.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from typing import Any, Optional

# Корень репозитория: lib/scheduling/cron_edit.py → три уровня вверх.
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CRONTAB_FILE = os.path.join(REPO_ROOT, "cron", "crontab.json")


def load_crontab(path: str) -> dict:
    """Читает crontab.json (ValueError при битом json, OSError — нет файла)."""
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("crontab.json — не объект")
    return data


def save_crontab(path: str, data: dict) -> None:
    """Атомарно перезаписывает crontab.json (temp-файл + os.replace)."""
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=".crontab-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
            file.write("\n")
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _find_job(data: dict, job_id: str) -> Optional[dict]:
    for item in data.get("jobs", []):
        if isinstance(item, dict) and str(item.get("id", "")).strip() == job_id:
            return item
    return None


def shift_job_schedule(job_id: str, moment: datetime,
                       offset: timedelta,
                       path: Optional[str] = None) -> Optional[str]:
    """Ставит расписание задания «job_id» на moment + offset.

    Дневные поля (dom/month/dow) не трогаем — «минута час * * *»
    из стандартного выражения сохраняется только если они были `*`
    (иначе возвращаем None: сдвигалка не для редких дат).

    Возвращает новое выражение либо None (задание/файл недоступны —
    звонящий обязан залогировать причину).
    """
    path = path or CRONTAB_FILE
    try:
        data = load_crontab(path)
    except (OSError, ValueError):
        return None
    job = _find_job(data, job_id)
    if job is None:
        return None
    fields = str(job.get("schedule", "")).split()
    if len(fields) != 5 or fields[2:] != ["*", "*", "*"]:
        return None
    target = moment + offset
    expr = f"{target.minute} {target.hour} * * *"
    job["schedule"] = expr
    try:
        save_crontab(path, data)
    except OSError:
        return None
    return expr


def _main(argv: Optional[list[str]] = None) -> int:
    import sys
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 3:
        print("использование: python -m lib.scheduling.cron_edit "
              "<job_id> <hours> <minutes>")
        return 2
    job_id, hours, minutes = args[0], int(args[1]), int(args[2])
    expr: Any = shift_job_schedule(
        job_id, datetime.now(), timedelta(hours=hours, minutes=minutes))
    if expr is None:
        print(f"[cron_edit] задание «{job_id}» не найдено или файл недоступен")
        return 1
    print(f"[cron_edit] «{job_id}» → {expr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
