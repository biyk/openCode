"""Тесты CommandMatcher: reload, get_command, конфиги."""


import pytest
import os
import subprocess
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


class TestCommandExec:
    """Перезагрузка, команды shell, llm/intent/match конфиги."""

    def test_reload_when_file_removed(self, temp_commands_file):
        """reload() при удалённом файле молча выходит (OSError)."""
        matcher = CommandMatcher(temp_commands_file)
        os.unlink(temp_commands_file)
        matcher.reload()
        assert matcher._data is not None

    def test_reload_picks_up_changes(self, temp_commands_file, mocker):
        """reload() перечитывает файл после его изменения."""
        matcher = CommandMatcher(temp_commands_file)
        with open(temp_commands_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["match"]["volumeup"].append("повысить")
        with open(temp_commands_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        matcher.reload()
        assert matcher.find_literal_id("пожалуйста повысить") == "volumeup"

    def test_reload_no_change_no_op(self, temp_commands_file):
        """Если файл не менялся, reload() ничего не делает."""
        matcher = CommandMatcher(temp_commands_file)
        matcher.reload()
        assert matcher._data is not None

    def test_get_command_unknown_id(self, temp_commands_file):
        """_get_command для несуществующего id возвращает None."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher._get_command("nonexistent_id") is None

    def test_get_command_returns_shell_command(self, temp_commands_file, mocker):
        """get_command возвращает команду по id с учётом платформы."""
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.get_command("volumeup")
        assert result == "pactl set-sink-volume @DEFAULT_SINK@ +10%"

    def test_get_command_none_for_unknown(self, temp_commands_file):
        """get_command для неизвестного id возвращает None."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.get_command("ghost") is None

    def test_execute_by_id_success(self, temp_commands_file, mocker):
        """execute_by_id выполняет команду по id."""
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        mocker.patch("lib.voice_cmd.commands.subprocess.run")
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.execute_by_id("volumeup") is True

    def test_execute_by_id_unknown_returns_false(self, temp_commands_file, mocker):
        """execute_by_id для неизвестного id возвращает False."""
        mocker.patch("lib.voice_cmd.commands.subprocess.run")
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.execute_by_id("ghost") is False

    def test_execute_by_id_command_error(self, temp_commands_file, mocker):
        """execute_by_id возвращает False при ошибке субпроцесса."""
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        subprocess_mock = mocker.patch("lib.voice_cmd.commands.subprocess.run")
        subprocess_mock.side_effect = subprocess.CalledProcessError(1, "cmd")
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.execute_by_id("volumeup") is False

    def test_get_command_missing_platform(self, temp_commands_file, mocker):
        """Если для платформы нет команды и нет default — None."""
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as f:
            json.dump({
                "triggers": DEFAULT_TRIGGERS,
                "commands": {"onlywin": {"windows": "echo hi"}},
                "match": {"onlywin": ["окно"]},
            }, f)
            temp_path = f.name
        try:
            matcher = CommandMatcher(temp_path)
            assert matcher._get_command("onlywin") is None
            assert matcher.find_literal_id("пожалуйста окно") == "onlywin"
        finally:
            os.unlink(temp_path)

    def test_execute_by_id_called_process_error(self, temp_commands_file, mocker):
        """При ошибке выполнения команды execute_by_id возвращает False."""
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        subprocess_mock = mocker.patch("lib.voice_cmd.commands.subprocess.run")
        subprocess_mock.side_effect = subprocess.CalledProcessError(1, "cmd")
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.execute_by_id("volumeup") is False

    def test_get_llm_config_returns_dict(self, temp_commands_file):
        """get_llm_config возвращает конфигурацию LLM."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.get_llm_config() == {"history_limit": 10}

    def test_get_llm_config_empty_when_missing(self, tmp_path):
        """Если поля llm нет — возвращается пустой словарь."""
        import tempfile
        import json
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as f:
            json.dump({"commands": {}, "match": {}}, f)
            temp_path = f.name
        try:
            matcher = CommandMatcher(temp_path)
            assert matcher.get_llm_config() == {}
        finally:
            os.unlink(temp_path)

    def test_get_intent_config_empty_when_missing(self, temp_commands_file):
        """Если поля intent нет — возвращается пустой словарь (фича выключена)."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.get_intent_config() == {}

    def test_get_intent_config_returns_dict(self, tmp_path):
        """get_intent_config возвращает конфигурацию интеллектуального классификатора."""
        import tempfile
        import json
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as f:
            json.dump({"intent": {"enabled": True, "include_media": False}}, f)
            temp_path = f.name
        try:
            matcher = CommandMatcher(temp_path)
            assert matcher.get_intent_config() == {
                "enabled": True, "include_media": False}
        finally:
            os.unlink(temp_path)

    def test_match_config_returns_match(self, temp_commands_file):
        """match_config возвращает словарь фраз для классификатора."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.match_config() == {
            "volumeup": ["громче", "сделай громче"],
            "volumedown": ["тише", "сделай тише"],
            "playpause": ["пауза", "плей"],
        }
