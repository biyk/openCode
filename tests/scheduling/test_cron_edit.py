# TOOLTIP: Тесты сдвига расписания в crontab.json (lib/scheduling/cron_edit.py)
"""Юнит-тесты lib/scheduling/cron_edit.py — правка crontab.json во tmp_path.

Проверяют, что shift_job_schedule ставит «минута час * * *» от
moment + offset, не трогает прочие поля задания и отказается писать,
если задание/файл недоступны или расписание нестандартное.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from lib.scheduling.cron_edit import (
    load_crontab,
    save_crontab,
    shift_job_schedule,
)

NOW = datetime(2026, 9, 27, 23, 40)


def _crontab(tmp_path, jobs) -> str:
    path = str(tmp_path / "crontab.json")
    with open(path, "w", encoding="utf-8") as file:
        json.dump({"jobs": jobs}, file, ensure_ascii=False, indent=4)
    return path


def _job(job_id="wake_video_and_volume", schedule="15 9 * * *") -> dict:
    return {"id": job_id, "schedule": schedule,
            "script": "wake_video_and_volume.ps1",
            "timeout": 180, "announce": False}


def test_shift_sets_now_plus_offset(tmp_path):
    """23:40 + 7ч30 → 07:10 следующего дня: «10 7 * * *»."""
    path = _crontab(tmp_path, [_job()])
    expr = shift_job_schedule(
        "wake_video_and_volume", NOW, timedelta(hours=7, minutes=30),
        path=path)
    assert expr == "10 7 * * *"
    data = load_crontab(path)
    assert data["jobs"][0]["schedule"] == "10 7 * * *"


def test_shift_keeps_other_fields(tmp_path):
    """Сдвиг меняет только schedule, script/timeout/announce целые."""
    path = _crontab(tmp_path, [_job()])
    shift_job_schedule("wake_video_and_volume", NOW,
                       timedelta(hours=7, minutes=30), path=path)
    job = load_crontab(path)["jobs"][0]
    assert job["script"] == "wake_video_and_volume.ps1"
    assert job["timeout"] == 180
    assert job["announce"] is False


def test_shift_missing_job_returns_none(tmp_path):
    path = _crontab(tmp_path, [_job("other")])
    assert shift_job_schedule("wake_video_and_volume", NOW,
                              timedelta(hours=7), path=path) is None


def test_shift_missing_file_returns_none(tmp_path):
    path = str(tmp_path / "no-such" / "crontab.json")
    assert shift_job_schedule("wake_video_and_volume", NOW,
                              timedelta(hours=7), path=path) is None


def test_shift_skips_non_daily_schedule(tmp_path):
    """Задание с привязкой к дате (dom/month/dow) не сдвигаем."""
    path = _crontab(tmp_path, [_job(schedule="15 9 1 1 *")])
    assert shift_job_schedule("wake_video_and_volume", NOW,
                              timedelta(hours=7), path=path) is None
    assert load_crontab(path)["jobs"][0]["schedule"] == "15 9 1 1 *"


def test_save_is_atomic(tmp_path):
    """После записи временных файлов не остаётся."""
    path = _crontab(tmp_path, [_job()])
    save_crontab(path, load_crontab(path))
    leftovers = [f for f in os.listdir(tmp_path) if f.startswith(".crontab-")]
    assert leftovers == []
