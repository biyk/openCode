import pytest
import os
import subprocess
import tempfile
import json
from lib.commands import CommandMatcher, DEFAULT_TRIGGERS


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
        result = matcher.find("пожалуйста громче")
        assert result == "pactl set-sink-volume @DEFAULT_SINK@ +10%"

    def test_find_partial_match(self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("алиса сделай громче музыку")
        assert result == "pactl set-sink-volume @DEFAULT_SINK@ +10%"

    def test_find_case_insensitive(self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("ПОЖАЛУЙСТА ГРОМЧЕ")
        assert result == "pactl set-sink-volume @DEFAULT_SINK@ +10%"

    def test_find_no_match(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("пожалуйста неизвестная команда")
        assert result is None

    def test_find_russian_template(self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("пожалуйста сделай тише")
        assert result == "pactl set-sink-volume @DEFAULT_SINK@ -10%"

    def test_find_windows_platform(self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Windows")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("алиса громче")
        assert result == "echo volumeup"

    def test_find_fallback_to_default(self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Darwin")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("пожалуйста громче")
        assert result == "echo volumeup"

    def test_find_string_command_fallback(self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Windows")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("пожалуйста пауза")
        assert result == "playerctl play-pause"

    def test_load_invalid_file(self):
        matcher = CommandMatcher("/nonexistent/file.json")
        assert matcher._data == {}

    def test_execute_no_command(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.execute("пожалуйста неизвестная команда")
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
        result = matcher.execute("пожалуйста громче")
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
        result = matcher.execute("пожалуйста громче")
        assert result is True
        speak_mock.assert_not_called()

    def test_find_without_trigger_returns_none(self, temp_commands_file):
        """Без триггера команда не должна находиться."""
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.find("громче")
        assert result is None

    def test_has_trigger_detects_trigger(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.has_trigger("пожалуйста громче") is True
        assert matcher.has_trigger("алиса тише") is True
        assert matcher.has_trigger("ПОЖАЛУЙСТА") is True

    def test_has_trigger_returns_false_without_trigger(self, temp_commands_file):
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.has_trigger("громче") is False
        assert matcher.has_trigger("сделай тише") is False

    def test_triggers_property_returns_default_when_missing(self):
        """Если в файле нет поля triggers, возвращаются дефолтные."""
        import tempfile
        import json
        commands = {
            "commands": {"test": "echo test"},
            "match": {"test": ["тест"]}
        }
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as f:
            json.dump(commands, f)
            temp_path = f.name
        try:
            matcher = CommandMatcher(temp_path)
            assert matcher.triggers == DEFAULT_TRIGGERS
        finally:
            os.unlink(temp_path)

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

        mocker.patch("lib.commands.platform.system", return_value="Linux")
        matcher.reload()
        result = matcher.find("пожалуйста повысить")
        assert result == "pactl set-sink-volume @DEFAULT_SINK@ +10%"

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
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.get_command("volumeup")
        assert result == "pactl set-sink-volume @DEFAULT_SINK@ +10%"

    def test_get_command_none_for_unknown(self, temp_commands_file):
        """get_command для неизвестного id возвращает None."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.get_command("ghost") is None

    def test_execute_by_id_success(self, temp_commands_file, mocker):
        """execute_by_id выполняет команду по id."""
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        mocker.patch("lib.commands.subprocess.run")
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.execute_by_id("volumeup") is True

    def test_execute_by_id_unknown_returns_false(self, temp_commands_file, mocker):
        """execute_by_id для неизвестного id возвращает False."""
        mocker.patch("lib.commands.subprocess.run")
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.execute_by_id("ghost") is False

    def test_execute_by_id_command_error(self, temp_commands_file, mocker):
        """execute_by_id возвращает False при ошибке субпроцесса."""
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        subprocess_mock = mocker.patch("lib.commands.subprocess.run")
        subprocess_mock.side_effect = subprocess.CalledProcessError(1, "cmd")
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.execute_by_id("volumeup") is False

    def test_get_command_missing_platform(self, temp_commands_file, mocker):
        """Если для платформы нет команды и нет default — None."""
        mocker.patch("lib.commands.platform.system", return_value="Linux")
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
            assert matcher.find("пожалуйста окно") == "onlywin"
        finally:
            os.unlink(temp_path)

    def test_execute_called_process_error(self, temp_commands_file, mocker):
        """При ошибке выполнения команды execute() возвращает False."""
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        subprocess_mock = mocker.patch("lib.commands.subprocess.run")
        subprocess_mock.side_effect = subprocess.CalledProcessError(1, "cmd")
        matcher = CommandMatcher(temp_commands_file)
        result = matcher.execute("пожалуйста громче")
        assert result is False

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
