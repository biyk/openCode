# TOOLTIP: Тесты регистрации будильника WakeToRun в Планировщике Windows
"""Юнит-тесты lib/scheduling/wake_alarm.py — powershell мокируется.

Проверяют: команда содержит -WakeToRun/-Force и верный момент -At,
успех (returncode 0) — None, отказ — текст причины, таймаут — тоже текст
(не исключение: «я спать» не должна падать из-за планировщика).
"""
from __future__ import annotations

import subprocess
from datetime import datetime

import lib.scheduling.wake_alarm as wa

MOMENT = datetime(2026, 9, 28, 7, 0, 0)


def _completed(returncode: int, stderr: str = "", stdout: str = ""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_command_contains_waketask_pieces(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _completed(0)

    monkeypatch.setattr(wa.subprocess, "run", fake_run)
    assert wa.schedule_wake_alarm(MOMENT) is None
    ps = captured["cmd"][-1]
    assert "-WakeToRun" in ps
    assert "-Force" in ps
    assert wa.TASK_NAME in ps
    assert "2026-09-28 07:00:00" in ps


def test_failure_returns_last_error_line(monkeypatch):
    err = "Первая строка\nAccess is denied.\n"
    monkeypatch.setattr(
        wa.subprocess, "run",
        lambda *a, **k: _completed(1, stderr=err))
    assert wa.schedule_wake_alarm(MOMENT) == "Access is denied."


def test_timeout_returns_text_not_exception(monkeypatch):
    def raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=30)

    monkeypatch.setattr(wa.subprocess, "run", raise_timeout)
    assert "не ответил" in wa.schedule_wake_alarm(MOMENT)


def test_sleep_event_arms_alarm_offset(monkeypatch):
    """arm_wake_alarm будит за 10 минут до cron-задания (+7ч20)."""
    from lib.sleep_event import arm_wake_alarm

    got = {}
    monkeypatch.setattr(
        "lib.sleep_event.schedule_wake_alarm",
        lambda moment: got.update(moment=moment) or None)
    arm_wake_alarm(datetime(2026, 9, 27, 23, 40))
    assert got["moment"].hour == 7 and got["moment"].minute == 0
