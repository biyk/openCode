"""Живые тесты Google Tasks (команда task-add): create → id → verify → delete.

Реально создают задачу через команду `python -m lib.tasks create "…"`,
проверяют чтение по id и удаляют её. Запускаются только с
VOICE_LIVE_GOOGLE=1, чтобы не засорять список задач на каждом прогоне.
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
from pathlib import Path

import pytest

from lib.commands import CommandMatcher
from lib.config_loader import get_device_commands_path
from lib.google_tasks import GoogleTasks

TASK_TEXT = "тестовая задача"
TASK_PHRASE = tuple(TASK_TEXT.split())
_TASK_ID_RE = re.compile(r"task_id:\s*(\S+)")
REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    os.environ.get("VOICE_LIVE_GOOGLE") != "1",
    reason="Реальные данные Google: включи VOICE_LIVE_GOOGLE=1",
)


@pytest.fixture
def google_tasks() -> GoogleTasks:
    """Авторизованные Google Tasks или skip, если токена нет.

    Если токен протух, но есть refresh_token — authorize() молча
    обновит его. Если авторизация невозможна — тест пропускается.
    """
    g = GoogleTasks()
    if not g.is_ready():
        try:
            g.authorize()
        except Exception as e:
            pytest.skip(f"Google Tasks недоступен: {e}")
    return g


def test_task_add_command_create_get_delete(google_tasks, live_announce):
    """Команда task-add: реальный запуск → id → verify → delete."""
    matcher = CommandMatcher(get_device_commands_path(platform.node()))
    cmd = matcher.get_command("task-add", TASK_PHRASE)
    assert cmd, "task-add: пустая shell-команда"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                         timeout=90, cwd=str(REPO_ROOT))
    assert res.returncode == 0, (
        f"task-add код {res.returncode}: {res.stderr.strip()}")
    match = _TASK_ID_RE.search(res.stdout)
    assert match, f"нет task_id в выводе: {res.stdout!r}"
    task_id = match.group(1)
    try:
        created = google_tasks.get_task(task_id)
        assert created is not None, "задача не найдена по id"
        assert created["title"] == TASK_TEXT
        assert created.get("status") == "needsAction"
    finally:
        assert google_tasks.delete_task(task_id) is True, "задача не удалилась"
    assert google_tasks.get_task(task_id) is None, "задача осталась после удаления"
