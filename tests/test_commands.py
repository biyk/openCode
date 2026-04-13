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
            "volumeup": {
                "linux": "pactl set-sink-volume @DEFAULT_SINK@ +10%",
                "windows": "echo volumeup",
                "default": "echo volumeup"
            },
            "volumedown": {
                "linux": "pactl set-sink-volume @DEFAULT_SINK@ -10%",
                "windows": "echo volumedown",
                "default": "echo volumedown"
            },
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

    def test_find_exact_match(self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("громче")
        assert result == "pactl set-sink-volume @DEFAULT_SINK@ +10%"

    def test_find_partial_match(self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("сделай громче музыку")
        assert result == "pactl set-sink-volume @DEFAULT_SINK@ +10%"

    def test_find_case_insensitive(self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("ГРОМЧЕ")
        assert result == "pactl set-sink-volume @DEFAULT_SINK@ +10%"

    def test_find_no_match(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("неизвестная команда")
        assert result is None

    def test_find_russian_template(self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("сделай тише")
        assert result == "pactl set-sink-volume @DEFAULT_SINK@ -10%"

    def test_find_windows_platform(self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Windows")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("громче")
        assert result == "echo volumeup"

    def test_find_fallback_to_default(self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Darwin")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("громче")
        assert result == "echo volumeup"

    def test_find_string_command_fallback(self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Windows")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("пауза")
        assert result == "playerctl play-pause"

    def test_load_invalid_file(self):
        matcher = CommandMatcher("/nonexistent/file.json")
        assert matcher._data == {}

    def test_execute_no_command(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.execute("неизвестная команда")
        assert result is False

    def test_execute_valid_command(self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        mocker.patch("lib.commands.subprocess.run")
        mocker.patch("lib.commands.TextToSpeech.speak_and_play")
        mocker.patch.dict("os.environ", {"VOICE_CONFIRMATION_PHRASE": "Готово"})
        from importlib import reload
        import lib.commands
        reload(lib.commands)
        from lib.commands import CommandMatcher as CM2
        matcher = CM2(temp_commands_file)
        result = matcher.execute("громче")
        assert result is True

    def test_execute_no_confirmation_by_default(self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        mocker.patch("lib.commands.subprocess.run")
        speak_mock = mocker.patch("lib.commands.TextToSpeech.speak_and_play")
        mocker.patch.dict("os.environ", {}, clear=True)
        from importlib import reload
        import lib.commands
        reload(lib.commands)
        from lib.commands import CommandMatcher as CM2
        matcher = CM2(temp_commands_file)
        result = matcher.execute("громче")
        assert result is True
        speak_mock.assert_not_called()
