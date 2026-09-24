"""Живой тест Google Calendar: тестовый план create → get → delete.

Реально создаёт событие в календаре, проверяет, что оно читается по id,
и удаляет его. Запускается только с VOICE_LIVE_GOOGLE=1, чтобы не
засорять календарь на каждом прогоне.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

from lib.google_calendar import GoogleCalendar

TEST_SUMMARY = "VOICE TEST — удалить"

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
