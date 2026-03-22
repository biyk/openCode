import pytest
import os
import tempfile
import json
from lib.commands import CommandMatcher


@pytest.fixture
def temp_commands_file():
    """Создаёт временный файл с командами для тестов."""
    commands = {
        "commands": {
            "volumeup": "pactl set-sink-volume @DEFAULT_SINK@ +10%",
            "volumedown": "pactl set-sink-volume @DEFAULT_SINK@ -10%",
            "playpause": "playerctl play-pause"
        },
        "match": {
            "volumeup": ["громче", "сделай громче"],
            "volumedown": ["тише", "сделай тише"],
            "playpause": ["пауза", "плей"]
        }
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(commands, f)
        temp_path = f.name
    yield temp_path
    os.unlink(temp_path)


class TestCommandMatcher:
    """Тесты для класса CommandMatcher."""

    def test_load_commands(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        assert matcher._data is not None
        assert "commands" in matcher._data
        assert "match" in matcher._data

    def test_find_exact_match(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("громче")
        assert result == "pactl set-sink-volume @DEFAULT_SINK@ +10%"

    def test_find_partial_match(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("сделай громче музыку")
        assert result == "pactl set-sink-volume @DEFAULT_SINK@ +10%"

    def test_find_case_insensitive(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("ГРОМЧЕ")
        assert result == "pactl set-sink-volume @DEFAULT_SINK@ +10%"

    def test_find_no_match(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("неизвестная команда")
        assert result is None

    def test_find_russian_template(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("сделай тише")
        assert result == "pactl set-sink-volume @DEFAULT_SINK@ -10%"

    def test_load_invalid_file(self):
        matcher = CommandMatcher("/nonexistent/file.json")
        assert matcher._data == {}

    def test_execute_no_command(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.execute("неизвестная команда")
        assert result is False

    def test_execute_valid_command(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.execute("громче")
        assert result is True
