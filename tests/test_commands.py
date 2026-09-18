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
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        mocker.patch("lib.commands.subprocess.run")
        speak_mock = mocker.patch("lib.commands.TextToSpeech.speak_and_play")
        mocker.patch.dict("os.environ", {"VOICE_CONFIRMATION_PHRASE": "Готово"})
        from importlib import reload
        import lib.commands
        reload(lib.commands)
        from lib.commands import CommandMatcher as CM2
        matcher = CM2(temp_commands_file)
        assert matcher.execute_by_id("volumeup") is True
        speak_mock.assert_called_once_with("Готово")

    def test_execute_by_id_no_confirmation_by_default(
            self, temp_commands_file, mocker):
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        mocker.patch("lib.commands.subprocess.run")
        speak_mock = mocker.patch("lib.commands.TextToSpeech.speak_and_play")
        mocker.patch.dict("os.environ", {}, clear=True)
        from importlib import reload
        import lib.commands
        reload(lib.commands)
        from lib.commands import CommandMatcher as CM2
        matcher = CM2(temp_commands_file)
        assert matcher.execute_by_id("volumeup") is True
        speak_mock.assert_not_called()

    def test_find_literal_without_trigger_returns_none(self, temp_commands_file):
        """Без триггера команда не должна находиться."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_literal_id("громче") is None

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
            None, [], True)
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
        """Совпадение ниже 90% — мимо (ложный вызов), не угадывать."""
        matcher = CommandMatcher(self._full_cfg()())
        assert matcher.find_command(["пожалуйста сделаыми громче"]) == (
            None, [], True)

    def test_find_command_no_command_around_key(self):
        """Ключ без команды вокруг — ложный вызов."""
        matcher = CommandMatcher(self._full_cfg()())
        assert matcher.find_command(["але все плохо"]) == (None, [], False)

    def test_find_command_no_command_when_key_last_line_wait(
            self, temp_commands_file):
        """Ключ последний, команды нет — ждём следующую строку."""
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_command(["да блин", "какая же ты тупая алиса"]) == (
            None, [], True)

    def test_find_command_settings_multiplier_applied(self, tmp_path, mocker):
        """Настройки меняют {{step}} через секцию settings."""
        import tempfile
        import json
        mocker.patch("lib.commands.platform.system", return_value="Linux")
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
            assert matcher.find_literal_id("пожалуйста окно") == "onlywin"
        finally:
            os.unlink(temp_path)

    def test_execute_by_id_called_process_error(self, temp_commands_file, mocker):
        """При ошибке выполнения команды execute_by_id возвращает False."""
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        subprocess_mock = mocker.patch("lib.commands.subprocess.run")
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

    def test_find_literal_returns_cmd_id(self, temp_commands_file, mocker):
        """find_literal_id возвращает id команды, а не shell-строку."""
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_literal_id("пожалуйста громче") == "volumeup"
        assert matcher.find_literal_id("пожалуйста неизвестная") is None

    def test_find_literal_exact_phrases(self, tmp_path, mocker):
        """Каждая фраза матчится только дословно."""
        import json
        mocker.patch("lib.commands.platform.system", return_value="Linux")
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

    def _write_cfg(self, cfg):
        """Пишет конфиг во временный файл, возвращает путь."""
        import json
        import tempfile
        path = tempfile.mktemp(suffix=".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return path

    def _fake_store(self, active):
        """Фейковое хранилище статусов: active — множество включённых."""
        from unittest.mock import MagicMock
        store = MagicMock()
        store.enabled = True
        store.ensure.side_effect = lambda names: [
            n for n in names if n not in active]
        return store

    def test_missing_requires_when_status_off(self, tmp_path, mocker):
        """missing_requires перечисляет невыполненные статусы."""
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        path = self._write_cfg({
            "triggers": ["пожалуйста"],
            "commands": {"playpause": "echo play", "stop": "echo stop"},
            "requires": {"playpause": ["media"], "stop": ["media"]},
            "match": {"playpause": ["пауза", "плей"], "stop": ["стоп"]},
        })
        try:
            matcher = CommandMatcher(path, status_store=self._fake_store(set()))
            assert matcher.find_literal_id("пожалуйста пауза") == "playpause"
            assert matcher.missing_requires("playpause") == ["media"]
            assert matcher.missing_requires("stop") == ["media"]
        finally:
            os.unlink(path)

    def test_missing_requires_empty_when_status_on(self, tmp_path, mocker):
        """При включённом статусе missing_requires пусто."""
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        path = self._write_cfg({
            "triggers": ["пожалуйста"],
            "commands": {"playpause": "echo play"},
            "requires": {"playpause": ["media"]},
            "match": {"playpause": ["пауза", "плей"]},
        })
        try:
            matcher = CommandMatcher(
                path, status_store=self._fake_store({"media"}))
            assert matcher.find_literal_id("пожалуйста пауза") == "playpause"
            assert matcher.missing_requires("playpause") == []
        finally:
            os.unlink(path)

    def test_requires_ignored_without_store(self, temp_commands_file, mocker):
        """Без хранилища статусы не проверяются (обратная совместимость)."""
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_literal_id("пожалуйста пауза") == "playpause"
        assert matcher.missing_requires("playpause") == []

    def test_execute_by_id_blocked_when_status_off(self, tmp_path, mocker):
        """execute_by_id не запускает команду без нужного статуса."""
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        run_mock = mocker.patch("lib.commands.subprocess.run")
        path = self._write_cfg({
            "triggers": ["пожалуйста"],
            "commands": {"openyoutube": "echo yt"},
            "requires": {"openyoutube": ["vpn"]},
            "match": {"openyoutube": ["открой ютуб"]},
        })
        try:
            matcher = CommandMatcher(path, status_store=self._fake_store(set()))
            assert matcher.execute_by_id("openyoutube") is False
            run_mock.assert_not_called()
            assert matcher.missing_requires("openyoutube") == ["vpn"]
        finally:
            os.unlink(path)

    def test_execute_sequence_runs_steps_in_order(self, tmp_path, mocker):
        """Sequence выполняет шаги по очереди и ставит provides."""
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        run_mock = mocker.patch("lib.commands.subprocess.run")
        path = self._write_cfg({
            "triggers": ["пожалуйста"],
            "commands": {"openyoutube": "echo yt", "playnews": "echo news"},
            "sequences": {"news": {"steps": ["openyoutube", "playnews"]}},
            "provides": {"openyoutube": ["browser_youtube"]},
            "match": {"news": ["включи новости"]},
        })
        try:
            store = self._fake_store({"vpn"})
            matcher = CommandMatcher(path, status_store=store)
            assert matcher.execute_by_id("news") is True
            assert run_mock.call_count == 2
            store.set.assert_called_once_with("browser_youtube", True)
            assert matcher.find_literal_id("пожалуйста включи новости") == "news"
        finally:
            os.unlink(path)

    def test_execute_sequence_stops_on_first_failure(self, tmp_path, mocker):
        """Sequence прерывается на первом упавшем шаге."""
        import subprocess
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        run_mock = mocker.patch("lib.commands.subprocess.run")
        run_mock.side_effect = subprocess.CalledProcessError(1, "cmd")
        path = self._write_cfg({
            "triggers": ["пожалуйста"],
            "commands": {"a": "echo a", "b": "echo b"},
            "sequences": {"seq": {"steps": ["a", "b"]}},
            "match": {"seq": ["цепочка"]},
        })
        try:
            matcher = CommandMatcher(path)
            assert matcher.execute_by_id("seq") is False
            assert run_mock.call_count == 1
        finally:
            os.unlink(path)

    def test_execute_sequence_blocked_step(self, tmp_path, mocker):
        """Sequence не запускается, если шаг заблокирован статусом."""
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        run_mock = mocker.patch("lib.commands.subprocess.run")
        path = self._write_cfg({
            "triggers": ["пожалуйста"],
            "commands": {"openyoutube": "echo yt"},
            "requires": {"openyoutube": ["vpn"]},
            "sequences": {"news": {"steps": ["openyoutube"]}},
            "match": {"news": ["включи новости"]},
        })
        try:
            matcher = CommandMatcher(path, status_store=self._fake_store(set()))
            assert matcher.execute_by_id("news") is False
            run_mock.assert_not_called()
        finally:
            os.unlink(path)

    def test_get_command_text_substitution_dict(self):
        """{{text}} в dict-шаблоне — слова после команды."""
        path = self._write_cfg({
            "triggers": ["пожалуйста", "алиса"],
            "commands": {
                "task-add": {
                    "linux": "python -m lib.tasks create \"{{text}}\"",
                    "default": "python -m lib.tasks create \"{{text}}\"",
                },
            },
            "match": {"task-add": ["создай задачу"]},
        })
        try:
            matcher = CommandMatcher(path)
            cmd = matcher.get_command(
                "task-add", ("убраться", "у", "кошки"))
            assert cmd == (
                "python -m lib.tasks create \"убраться у кошки\"")
        finally:
            os.unlink(path)

    def test_get_command_text_substitution_plain_string(self):
        """{{text}} работает и в plain-строке (generic commands.json)."""
        path = self._write_cfg({
            "triggers": ["пожалуйста", "алиса"],
            "commands": {
                "calendar-reminder":
                    "python -m lib.reminders \"{{text}}\"",
            },
            "match": {"calendar-reminder": ["напомни"]},
        })
        try:
            matcher = CommandMatcher(path)
            cmd = matcher.get_command(
                "calendar-reminder", ("через", "час", "позвонить"))
            assert cmd == "python -m lib.reminders \"через час позвонить\""
        finally:
            os.unlink(path)

    def test_get_command_text_strips_quotes(self):
        """Кавычки внутри текста вырезаются (не рвут shell-команду)."""
        path = self._write_cfg({
            "triggers": ["алиса"],
            "commands": {
                "task-add": {
                    "default": "python -m lib.tasks create \"{{text}}\"",
                },
            },
            "match": {"task-add": ["создай задачу"]},
        })
        try:
            matcher = CommandMatcher(path)
            cmd = matcher.get_command("task-add", ("купить", '"хлеб"'))
            assert cmd == "python -m lib.tasks create \"купить хлеб\""
        finally:
            os.unlink(path)

    def test_find_command_reminder(self):
        """[Алиса] _напомни_ {через 30 минут} {сходить в магазин}."""
        path = self._write_cfg({
            "triggers": ["пожалуйста", "алиса"],
            "commands": {
                "calendar-reminder": {
                    "default": "python -m lib.reminders \"{{text}}\"",
                },
            },
            "match": {
                "calendar-reminder": [
                    "напомни", "напомни мне", "поставь напоминание",
                ],
            },
        })
        try:
            matcher = CommandMatcher(path)
            assert matcher.find_command([
                "алиса напомни через тридцать минут сходить в магазин",
            ]) == ("calendar-reminder", [
                "через", "тридцать", "минут", "сходить", "в", "магазин",
            ], False)
        finally:
            os.unlink(path)

    def test_find_command_reminder_multiword_template(self):
        """_поставь напоминание_ — двухсловный шаблон, текст после."""
        path = self._write_cfg({
            "triggers": ["пожалуйста", "алиса"],
            "commands": {
                "calendar-reminder": {
                    "default": "python -m lib.reminders \"{{text}}\"",
                },
            },
            "match": {
                "calendar-reminder": [
                    "напомни", "напомни мне", "поставь напоминание",
                ],
            },
        })
        try:
            matcher = CommandMatcher(path)
            assert matcher.find_command([
                "алиса поставь напоминание позвонить маме",
            ]) == ("calendar-reminder", ["позвонить", "маме"], False)
        finally:
            os.unlink(path)

    def test_find_command_task_add(self):
        """[пожалуйста] _создай задачу_ {Убраться у кошки}."""
        path = self._write_cfg({
            "triggers": ["пожалуйста", "алиса"],
            "commands": {
                "task-add": {
                    "default": "python -m lib.tasks create \"{{text}}\"",
                },
            },
            "match": {
                "task-add": ["создай задачу", "добавь задачу"],
            },
        })
        try:
            matcher = CommandMatcher(path)
            assert matcher.find_command([
                "пожалуйста создай задачу убраться у кошки",
            ]) == ("task-add", ["убраться", "у", "кошки"], False)
        finally:
            os.unlink(path)

    def test_execute_task_add_builds_shell_command(self, mocker):
        """execute собирает shell-команду с текстом задачи."""
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        run_mock = mocker.patch("lib.commands.subprocess.run")
        path = self._write_cfg({
            "triggers": ["пожалуйста"],
            "commands": {
                "task-add": {
                    "linux": "python -m lib.tasks create \"{{text}}\"",
                    "default": "python -m lib.tasks create \"{{text}}\"",
                },
            },
            "match": {"task-add": ["создай задачу"]},
        })
        try:
            matcher = CommandMatcher(path)
            assert matcher.execute_by_id(
                "task-add", ("убраться", "у", "кошки")) is True
            run_mock.assert_called_once_with(
                "python -m lib.tasks create \"убраться у кошки\"",
                shell=True, check=True)
        finally:
            os.unlink(path)
