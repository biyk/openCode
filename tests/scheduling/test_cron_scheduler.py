"""Юнит-тесты планировщика cron (lib.scheduling.cron)."""

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from lib.scheduling.cron import CronScheduler

D = datetime


def _wait_active(scheduler, timeout: float = 2.0) -> None:
    """Ждёт завершения фоновых заданий (детерминирует гонки)."""
    deadline = time.time() + timeout
    while scheduler._active:
        if time.time() > deadline:
            raise AssertionError("задание не завершилось за "
                                 f"{timeout:.1f} с")
        time.sleep(0.005)


def _write_crontab(tmp_path, jobs) -> str:
    path = tmp_path / "crontab.json"
    path.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    return str(path)


def test_shell_job_fires_once_per_minute(tmp_path, mocker):
    crontab = _write_crontab(tmp_path, [
        {"id": "job", "schedule": "0 21 * * *", "shell": "echo hi"}])
    clock = iter([D(2026, 9, 24, 21, 0, 0), D(2026, 9, 24, 21, 0, 30)])
    run = mocker.patch("lib.scheduling.cron_jobs.subprocess.run",
                       return_value=mocker.Mock(returncode=0))
    scheduler = CronScheduler(crontab, now=lambda: next(clock))
    scheduler.tick()
    run.assert_called_once_with(
        "echo hi", shell=True, cwd=str(tmp_path),
        capture_output=True, timeout=120.0)
    scheduler.tick()
    assert run.call_count == 1


def test_job_fires_again_next_minute(tmp_path, mocker):
    crontab = _write_crontab(tmp_path, [
        {"id": "job", "schedule": "* * * * *", "shell": "x"}])
    clock = iter([D(2026, 9, 24, 21, 0, 0), D(2026, 9, 24, 21, 1, 0)])
    run = mocker.patch("lib.scheduling.cron_jobs.subprocess.run",
                       return_value=mocker.Mock(returncode=0))
    scheduler = CronScheduler(crontab, now=lambda: next(clock))
    scheduler.tick()
    _wait_active(scheduler)
    scheduler.tick()
    _wait_active(scheduler)
    assert run.call_count == 2


def test_disabled_job_not_fired(tmp_path, mocker):
    crontab = _write_crontab(tmp_path, [
        {"id": "job", "schedule": "* * * * *", "shell": "x",
         "enabled": False}])
    run = mocker.patch("lib.scheduling.cron_jobs.subprocess.run")
    scheduler = CronScheduler(crontab, now=lambda: D(2026, 9, 24, 21, 0, 0))
    scheduler.tick()
    run.assert_not_called()


def test_script_job_runs_powershell(tmp_path, mocker):
    scripts = tmp_path / "jobs"
    scripts.mkdir()
    (scripts / "task.ps1").write_text("# x", encoding="utf-8")
    crontab = _write_crontab(tmp_path, [
        {"id": "job", "schedule": "* * * * *", "script": "task.ps1"}])
    run = mocker.patch("lib.scheduling.cron_jobs.subprocess.run", return_value=mocker.Mock())
    scheduler = CronScheduler(crontab, now=lambda: D(2026, 9, 24, 21, 0, 0))
    scheduler.tick()
    _wait_active(scheduler)
    command = run.call_args.args[0]
    assert command[0] == "powershell"
    assert command[-1] == os.path.join(str(tmp_path), "jobs", "task.ps1")
    assert run.call_args.kwargs["cwd"] == str(tmp_path)


def test_announce_success_and_failure(tmp_path, mocker):
    crontab = _write_crontab(tmp_path, [
        {"id": "ok", "schedule": "0 12 * * *", "shell": "a",
         "announce": True},
        {"id": "bad", "schedule": "1 12 * * *", "shell": "b",
         "announce": True}])
    mocker.patch("lib.scheduling.cron_jobs.subprocess.run",
                 side_effect=[mocker.Mock(returncode=0),
                              mocker.Mock(returncode=1)])
    tts = mocker.Mock()
    scheduler = CronScheduler(crontab, tts=tts)
    jobs = {job.job_id: job for job in scheduler.jobs}
    scheduler._run_job(jobs["ok"])
    scheduler._run_job(jobs["bad"])
    assert tts.speak_and_play.call_args_list[0][0][0] == "задание выполнено"
    assert tts.speak_and_play.call_args_list[1][0][0] == \
        "задание не выполнено"


def test_errors_release_job(tmp_path, mocker):
    for error in (subprocess.TimeoutExpired("x", 1.0), RuntimeError("no")):
        crontab = _write_crontab(tmp_path, [
            {"id": "job", "schedule": "* * * * *", "shell": "x"}])
        mocker.patch("lib.scheduling.cron_jobs.subprocess.run", side_effect=error)
        scheduler = CronScheduler(crontab,
                                  now=lambda: D(2026, 9, 24, 21, 0, 0))
        job = scheduler.jobs[0]
        scheduler._active.add(job.job_id)
        scheduler._run_job(job)
        assert job.job_id not in scheduler._active


def test_running_job_skips_next_fire(tmp_path, mocker):
    crontab = _write_crontab(tmp_path, [
        {"id": "job", "schedule": "0 21 * * *", "shell": "x"}])
    run = mocker.patch("lib.scheduling.cron_jobs.subprocess.run")
    scheduler = CronScheduler(crontab, now=lambda: D(2026, 9, 24, 21, 0, 0))
    scheduler._active.add("job")
    scheduler.tick()
    run.assert_not_called()
    assert "job" in scheduler._active


def test_missing_script_reports_failure(tmp_path, mocker):
    crontab = _write_crontab(tmp_path, [
        {"id": "job", "schedule": "* * * * *", "script": "absent.ps1"}])
    run = mocker.patch("lib.scheduling.cron_jobs.subprocess.run")
    scheduler = CronScheduler(crontab, now=lambda: D(2026, 9, 24, 21, 0, 0))
    job = scheduler.jobs[0]
    assert scheduler._runner.execute(job) is False
    run.assert_not_called()


def test_invalid_jobs_skipped(tmp_path):
    crontab = _write_crontab(tmp_path, [
        {"id": "good", "schedule": "0 12 * * *", "shell": "x"},
        {"id": "bad_sched", "schedule": "61 * * * *", "shell": "y"},
        {"id": "conflict", "schedule": "* * * * *", "script": "a.ps1",
         "shell": "echo x"}])
    scheduler = CronScheduler(crontab)
    assert [job.job_id for job in scheduler.jobs] == ["good"]


def test_missing_crontab_no_jobs(tmp_path):
    scheduler = CronScheduler(str(tmp_path / "nope.json"))
    assert scheduler.jobs == []
    scheduler.start()
    scheduler.stop()
    assert scheduler._thread is None


def test_reload_applies_after_mtime_change(tmp_path):
    crontab = Path(_write_crontab(tmp_path, [
        {"id": "a", "schedule": "0 12 * * *", "shell": "x"}]))
    scheduler = CronScheduler(str(crontab))
    assert [job.job_id for job in scheduler.jobs] == ["a"]
    old = crontab.stat().st_mtime
    crontab.write_text(json.dumps({"jobs": [
        {"id": "b", "schedule": "0 12 * * *", "shell": "y"}]}),
        encoding="utf-8")
    os.utime(crontab, (old + 10, old + 10))
    scheduler.reload()
    assert [job.job_id for job in scheduler.jobs] == ["b"]


def test_base_dir_changes_cwd_not_script_dir(tmp_path, mocker):
    scripts = tmp_path / "jobs"
    scripts.mkdir()
    (scripts / "task.ps1").write_text("# x", encoding="utf-8")
    crontab = _write_crontab(tmp_path, [
        {"id": "job", "schedule": "* * * * *", "script": "task.ps1"}])
    run = mocker.patch("lib.scheduling.cron_jobs.subprocess.run",
                       return_value=mocker.Mock(returncode=0))
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    scheduler = CronScheduler(crontab, now=lambda: D(2026, 9, 24, 21, 0, 0),
                              base_dir=str(other_dir))
    scheduler.tick()
    _wait_active(scheduler)
    command = run.call_args.args[0]
    assert command[-1] == os.path.join(str(tmp_path), "jobs", "task.ps1")
    assert run.call_args.kwargs["cwd"] == str(other_dir)


def test_failure_logs_stderr_tail(tmp_path, mocker, capsys):
    crontab = _write_crontab(tmp_path, [
        {"id": "job", "schedule": "* * * * *", "shell": "x"}])
    mocker.patch("lib.scheduling.cron_jobs.subprocess.run",
                 return_value=mocker.Mock(returncode=1, stderr=b"boom"))
    scheduler = CronScheduler(crontab)
    ok = scheduler._runner.execute(scheduler.jobs[0])
    assert ok is False
    assert "stderr: boom" in capsys.readouterr().out
