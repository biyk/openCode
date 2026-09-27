"""Заготовка: что сборка РАСПОЗНАЁТ во фразе (без выполнения shell).

Двигает реальный Orchestrator с реальным commands.json текущего устройства,
но execute_by_id подменён записью вызовов — видно, какую команду и с каким
текстом выбрал пайплайн, не запуская команду. Добавляй пары
(фраза → (cmd_id, настройки)) в параметризацию ниже.

execute_by_id возвращает (cmd_id, settings) когда у команды есть свободный
текст, и (cmd_id,) когда настроек нет.
"""

import platform
from unittest.mock import MagicMock

import pytest

from lib.core.orchestrator import Orchestrator
from lib.voice_cmd.commands import CommandMatcher
from lib.voice_cmd.config_loader import get_device_commands_path


@pytest.fixture()
def recognize():
    """Фабрика: (фраза) → кортеж аргументов execute_by_id, без запуска shell."""
    matcher = CommandMatcher(get_device_commands_path(platform.node()))
    calls = []
    matcher.execute_by_id = lambda *a, **k: (calls.append(a), True)[1]
    orch = Orchestrator(matcher=matcher, output=MagicMock(), tts=MagicMock())

    def _run(text):
        calls.clear()
        orch.process_text(text)
        assert calls, f"сборка не выполнила ни одной команды для: {text!r}"
        return calls[0]
    return _run


@pytest.mark.parametrize("text,expected", [
    ("алиса добавь задачу убраться на балконе",
     ("task-add", ("убраться", "на", "балконе"))),
])
def test_recognized_command(recognize, text, expected):
    assert recognize(text) == expected
