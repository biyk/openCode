"""Тесты CommandMatcher: дословные совпадения и выполнение."""


import pytest
import os
import tempfile
import json
from lib.voice_cmd.commands import CommandMatcher, DEFAULT_TRIGGERS


@pytest.fixture
def temp_commands_file():
    """Создаёт временный файл с командами для тестов."""
    commands = {
        "triggers": DEFAULT_TRIGGERS,
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
        },
        "llm": {
            "history_limit": 10
        }
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(commands, f)
        temp_path = f.name
    yield temp_path
    if os.path.exists(temp_path):
        os.unlink(temp_path)


class TestCommandLiteral:
    """Загрузка, find_literal, core_phrase, execute_by_id."""

    def test_load_commands(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        assert matcher._data is not None
        assert "commands" in matcher._data
        assert "match" in matcher._data

    def test_find_literal_exact_match(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_literal_id("пожалуйста громче") == "volumeup"

    def test_find_literal_no_substring_match(self, temp_commands_file):
        """Подстрока НЕ считается: лишние слова вокруг — мимо."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_literal_id("алиса сделай громче музыку") is None
        assert matcher.find_literal_id("пожалуйста очень громче") is None

    def test_find_literal_case_insensitive(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_literal_id("ПОЖАЛУЙСТА ГРОМЧЕ") == "volumeup"

    def test_find_literal_triggers_stripped(self, temp_commands_file):
        """Триггеры вырезаются с любой позиции."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_literal_id("громче пожалуйста") == "volumeup"
        assert matcher.find_literal_id("алиса громче пожалуйста") == "volumeup"

    def test_find_literal_no_match(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_literal_id("пожалуйста неизвестная команда") is None

    def test_find_literal_russian_template(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_literal_id("пожалуйста сделай тише") == "volumedown"

    def test_find_literal_string_command(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_literal_id("пожалуйста пауза") == "playpause"

    def test_core_phrase_strips_triggers(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.core_phrase("алиса включи ютуб пожалуйста") == "включи ютуб"
        assert matcher.core_phrase("ПОЖАЛУЙСТА  ГРОМЧЕ ") == "громче"
        assert matcher.core_phrase("пожалуйста") == ""

    def test_load_invalid_file(self):
        matcher = CommandMatcher("/nonexistent/file.json")
        assert matcher._data == {}

    def test_execute_by_id_confirmation_phrase(self, temp_commands_file, mocker):
        """VOICE_CONFIRMATION_PHRASE озвучивается после команды."""
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        mocker.patch("lib.voice_cmd.commands.subprocess.run")
        speak_mock = mocker.patch("lib.voice_cmd.commands.TextToSpeech.speak_and_play")
        mocker.patch.dict("os.environ", {"VOICE_CONFIRMATION_PHRASE": "Готово"})
        from importlib import reload
        import lib.voice_cmd.commands
        reload(lib.voice_cmd.commands)
        from lib.voice_cmd.commands import CommandMatcher as CM2
        matcher = CM2(temp_commands_file)
        assert matcher.execute_by_id("volumeup") is True
        speak_mock.assert_called_once_with("Готово")

    def test_execute_by_id_no_confirmation_by_default(
            self, temp_commands_file, mocker):
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        mocker.patch("lib.voice_cmd.commands.subprocess.run")
        speak_mock = mocker.patch("lib.voice_cmd.commands.TextToSpeech.speak_and_play")
        mocker.patch.dict("os.environ", {}, clear=True)
        from importlib import reload
        import lib.voice_cmd.commands
        reload(lib.voice_cmd.commands)
        from lib.voice_cmd.commands import CommandMatcher as CM2
        matcher = CM2(temp_commands_file)
        assert matcher.execute_by_id("volumeup") is True
        speak_mock.assert_not_called()

    def test_find_literal_returns_cmd_id(self, temp_commands_file, mocker):
        """find_literal_id возвращает id команды, а не shell-строку."""
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_literal_id("пожалуйста громче") == "volumeup"
        assert matcher.find_literal_id("пожалуйста неизвестная") is None

    def test_find_literal_exact_phrases(self, tmp_path, mocker):
        """Каждая фраза матчится только дословно."""
        import json
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        cfg = {
            "triggers": ["пожалуйста"],
            "commands": {
                "playpause": "echo play",
                "openyt": "echo youtube",
            },
            "match": {
                "playpause": ["включи"],
                "openyt": ["включи ютуб"],
            },
        }
        import tempfile
        path = tempfile.mktemp(suffix=".json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            matcher = CommandMatcher(path)
            assert matcher.find_literal_id("пожалуйста включи ютуб") == "openyt"
            assert matcher.find_literal_id("пожалуйста включи") == "playpause"
            # Короткий шаблон внутри длинной фразы — не совпадение.
            assert matcher.find_literal_id("пожалуйста включи и ютюб") is None
        finally:
            os.unlink(path)
