"""Тесты CommandMatcher: концепция «трёх строк» (find_command)."""
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


class TestCommandFind:
    """Ключ/команда/настройки, fuzzy-порог, триггеры."""
    def _full_cfg(self):
        """Конфиг с командами громкости/паузы/стопа для тестов концепции."""
        import tempfile
        import json

        def _write():
            path = tempfile.mktemp(suffix=".json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "triggers": ["пожалуйста", "алиса"],
                    "commands": {
                        "volumeup": {
                            "linux": "pactl +10%",
                            "windows": "echo volumeup",
                            "default": "echo volumeup",
                        },
                        "volumedown": {
                            "linux": "pactl -10%",
                            "windows": "echo volumedown",
                            "default": "echo volumedown",
                        },
                        "playpause": "echo playpause",
                        "stop": "echo stop",
                    },
                    "match": {
                        "volumeup": ["громче", "сделай громче"],
                        "volumedown": ["тише", "сделай тише"],
                        "playpause": ["пауза", "плей"],
                        "stop": ["стоп", "остановить", "выключи"],
                    },
                }, f)
            return path
        return _write

    def test_find_literal_without_trigger_returns_none(self, temp_commands_file):
        """Без триггера команда не должна находиться."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_literal_id("громче") is None

    def test_find_command_key_with_command_same_line(self, temp_commands_file):
        """[Алиса] _сделай громче_ — команда в строке ключа."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_command(["алиса сделай громче"]) == (
            "volumeup", [], False)

    def test_find_command_command_before_key_previous_line(self):
        """_выключи_ / [Пожалуйста] — команда над ключом."""
        matcher = CommandMatcher(self._full_cfg()())
        assert matcher.find_command([
            "как же меня это достало", "выключи", "пожалуйста"
        ]) == ("stop", [], False)

    def test_find_command_command_after_key_next_line(self, temp_commands_file):
        """[Алиса] в строке, команда — следующей строкой."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_command(["какая же ты тупая алиса"]) == (
            None, [], False)
        assert matcher.find_command([
            "какая же ты тупая алиса", "сделай громче немного"
        ]) == ("volumeup", ["немного"], False)

    def test_find_command_settings_strong(self, temp_commands_file):
        """{сильно} удваивает шаг громкости."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_command(["алиса сделай громче сильно"]) == (
            "volumeup", ["сильно"], False)

    def test_find_command_fuzzy_match_above_threshold(self):
        """Фраза близкая к шаблону (≥90%) распознаётся (не дословно)."""
        matcher = CommandMatcher(self._full_cfg()())
        assert matcher.find_command(["пожалуйста сделой громче"]) == (
            "volumeup", [], False)

    def test_find_command_fuzzy_below_threshold_rejected(self):
        """Совпадение ниже 90% — мимо: не угадываем, уходим к Laya."""
        matcher = CommandMatcher(self._full_cfg()())
        assert matcher.find_command(["пожалуйста сделаыми громче"]) == (
            None, [], False)

    def test_find_command_no_command_around_key(self):
        """Ключ без команды вокруг — ложный вызов."""
        matcher = CommandMatcher(self._full_cfg()())
        assert matcher.find_command(["але все плохо"]) == (None, [], False)

    def test_find_command_no_command_when_key_last_line_not_wait(
            self, temp_commands_file):
        """Ключ последний, слова есть, но команды нет — не ждём, к Laya."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_command(["да блин", "какая же ты тупая алиса"]) == (
            None, [], False)

    def test_find_command_bare_trigger_waits(self, temp_commands_file):
        """Голый ключ без содержания — ждём следующую строку."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_command(["пожалуйста"]) == (None, [], True)
        assert matcher.find_command(["алиса"]) == (None, [], True)
        assert matcher.find_command(["алиса пожалуйста"]) == (None, [], True)

    def test_find_command_settings_multiplier_applied(self, tmp_path, mocker):
        """Настройки меняют {{step}} через секцию settings."""
        import tempfile
        import json
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        path = tempfile.mktemp(suffix=".json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "triggers": ["пожалуйста", "алиса"],
                    "commands": {
                        "volumeup": {
                            "linux": "pactl +{{step}}%",
                            "default": "pactl +{{step}}%",
                            "step": 10
                        }
                    },
                    "match": {"volumeup": ["громче", "сделай громче"]},
                    "settings": {"volumeup": {
                        "немного": {"step": 0.5},
                        "сильно": {"step": 2.0}
                    }},
                }, f)
            matcher = CommandMatcher(path)
            assert matcher.get_command("volumeup") == "pactl +10%"
            assert matcher.get_command("volumeup", ("немного",)) == "pactl +5%"
            assert matcher.get_command("volumeup", ("сильно",)) == "pactl +20%"
        finally:
            os.unlink(path)

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
        commands = {"commands": {"test": "echo test"},
                    "match": {"test": ["тест"]}}
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
