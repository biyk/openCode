"""Живые тесты Google Calendar: create → get(id) → verify → delete.

Реально создают события в календаре, проверяют чтение по id и удаляют
их. Запускаются только с VOICE_LIVE_GOOGLE=1, чтобы не засорять
календарь на каждом прогоне.
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from lib.commands import CommandMatcher
from lib.config_loader import get_device_commands_path
from lib.google_calendar import GoogleCalendar

TEST_SUMMARY = "VOICE TEST — удалить"
REPO_ROOT = Path(__file__).resolve().parents[1]
# Текст и «слова после команды» для реальной команды calendar-reminder.
REMINDER_TEXT = "тестовое напоминание"
REMINDER_PHRASE = ("через", "3", "часа") + tuple(REMINDER_TEXT.split())
_EVENT_ID_RE = re.compile(r"event_id:\s*(\S+)")

pytestmark = pytest.mark.skipif(
    os.environ.get("VOICE_LIVE_GOOGLE") != "1",
    reason="Реальные данные Google: включи VOICE_LIVE_GOOGLE=1",
)


@pytest.fixture
def google() -> GoogleCalendar:
    """Авторизованный календарь или skip, если токена нет.

    Если токен протух, но есть refresh_token — authorize() молча
    обновит его. Если авторизация невозможна — тест пропускается.
    """
    g = GoogleCalendar()
    if not g.is_ready():
        try:
            g.authorize()
        except Exception as e:
            pytest.skip(f"Google Calendar недоступен: {e}")
    return g


def test_calendar_plan_create_get_delete(google, live_announce):
    """Тестовый план: создание → получение id → чтение → удаление."""
    when = datetime.now().astimezone() + timedelta(hours=2)
    event_id = google.create_reminder(TEST_SUMMARY, when)
    assert event_id, "create_reminder не вернул id"
    try:
        created = google.get_event(event_id)
        assert created is not None, "созданный план не найден по id"
        assert created["id"] == event_id
        assert created["summary"] == TEST_SUMMARY
    finally:
        assert google.delete_event(event_id) is True, "план не удалился"
    assert google.get_event(event_id) is None, "план остался после удаления"


def test_calendar_reminder_command_create_get_delete(google, live_announce):
    """Команда calendar-reminder: реальный запуск → id → verify → delete."""
    matcher = CommandMatcher(get_device_commands_path(platform.node()))
    cmd = matcher.get_command("calendar-reminder", REMINDER_PHRASE)
    assert cmd, "calendar-reminder: пустая shell-команда"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                         timeout=90, cwd=str(REPO_ROOT))
    assert res.returncode == 0, (
        f"calendar-reminder код {res.returncode}: {res.stderr.strip()}")
    match = _EVENT_ID_RE.search(res.stdout)
    assert match, f"нет event_id в выводе: {res.stdout!r}"
    event_id = match.group(1)
    try:
        created = google.get_event(event_id)
        assert created is not None, "напоминание не найдено по id"
        assert created["summary"] == REMINDER_TEXT
    finally:
        assert google.delete_event(event_id) is True, "напоминание не удалилось"
    assert google.get_event(event_id) is None, "напоминание осталось"
