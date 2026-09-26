"""Тесты вывода cron-заданий в лог (lib.cron_jobs.JobRunner)."""

import json
import subprocess

from lib.cron import CronScheduler


def _scheduler(tmp_path, shell_cmd):
    path = tmp_path / "crontab.json"
    path.write_text(json.dumps({"jobs": [
        {"id": "job", "schedule": "* * * * *", "shell": shell_cmd}]}),
        encoding="utf-8")
    return CronScheduler(str(path))


def test_success_stdout_logged(tmp_path, mocker, capsys):
    run = mocker.patch("lib.cron_jobs.subprocess.run", return_value=mocker.Mock(
        returncode=0, stdout=b"[step 1] ok\n[done]", stderr=b""))
    scheduler = _scheduler(tmp_path, "x")
    assert scheduler._runner.execute(scheduler.jobs[0]) is True
    out = capsys.readouterr().out
    assert run.called
    assert "вывод: [step 1] ok" in out and "[done]" in out


def test_failure_logs_stdout_and_stderr(tmp_path, mocker, capsys):
    mocker.patch("lib.cron_jobs.subprocess.run", return_value=mocker.Mock(
        returncode=1, stdout=b"[step 2] NOT OPENED", stderr=b"boom"))
    scheduler = _scheduler(tmp_path, "x")
    assert scheduler._runner.execute(scheduler.jobs[0]) is False
    out = capsys.readouterr().out
    assert "вывод: [step 2] NOT OPENED" in out
    assert "stderr: boom" in out


def test_non_bytes_stdout_not_logged(tmp_path, mocker, capsys):
    # Моки старых тестов отдают Mock вместо bytes — падать нельзя.
    mocker.patch("lib.cron_jobs.subprocess.run",
                 return_value=mocker.Mock(returncode=0))
    scheduler = _scheduler(tmp_path, "x")
    assert scheduler._runner.execute(scheduler.jobs[0]) is True
    assert "вывод:" not in capsys.readouterr().out


def test_timeout_logs_partial_stdout(tmp_path, mocker, capsys):
    # При таймауте Windows-версия run() отдаёт то, что скрипт уже
    # успел напечатать, — главная зацепка, на каком шаге всё виснет.
    error = subprocess.TimeoutExpired(cmd="x", timeout=5)
    error.stdout = b"[step 3.1] player: paused"
    mocker.patch("lib.cron_jobs.subprocess.run", side_effect=error)
    scheduler = _scheduler(tmp_path, "x")
    # Таймаут перехватывает run(), а не execute().
    assert scheduler._runner.run(scheduler.jobs[0]) is False
    out = capsys.readouterr().out
    assert "таймаут" in out
    assert "вывод: [step 3.1] player: paused" in out
