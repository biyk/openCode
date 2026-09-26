"""Тесты CommandMatcher: статусы, блокировки, sequences."""


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


class TestCommandRequires:
    """missing_requires, blocked, выполнение цепочек."""

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
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
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
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
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
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        matcher = CommandMatcher(temp_commands_file)
        assert matcher.find_literal_id("пожалуйста пауза") == "playpause"
        assert matcher.missing_requires("playpause") == []

    def test_execute_by_id_blocked_when_status_off(self, tmp_path, mocker):
        """execute_by_id не запускает команду без нужного статуса."""
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        run_mock = mocker.patch("lib.voice_cmd.commands.subprocess.run")
        path = self._write_cfg({
            "triggers": ["пожалуйста"],
            "commands": {"openyoutube": "echo yt"},
            "requires": {"openyoutube": ["proxy"]},
            "match": {"openyoutube": ["открой ютуб"]},
        })
        try:
            matcher = CommandMatcher(path, status_store=self._fake_store(set()))
            assert matcher.execute_by_id("openyoutube") is False
            run_mock.assert_not_called()
            assert matcher.missing_requires("openyoutube") == ["proxy"]
        finally:
            os.unlink(path)

    def test_execute_sequence_runs_steps_in_order(self, tmp_path, mocker):
        """Sequence выполняет шаги по очереди и ставит provides."""
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        run_mock = mocker.patch("lib.voice_cmd.commands.subprocess.run")
        path = self._write_cfg({
            "triggers": ["пожалуйста"],
            "commands": {"openyoutube": "echo yt", "playnews": "echo news"},
            "sequences": {"news": {"steps": ["openyoutube", "playnews"]}},
            "provides": {"openyoutube": ["browser_youtube"]},
            "match": {"news": ["включи новости"]},
        })
        try:
            store = self._fake_store({"proxy"})
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
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        run_mock = mocker.patch("lib.voice_cmd.commands.subprocess.run")
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
        mocker.patch("lib.voice_cmd.commands.platform.system", return_value="Linux")
        run_mock = mocker.patch("lib.voice_cmd.commands.subprocess.run")
        path = self._write_cfg({
            "triggers": ["пожалуйста"],
            "commands": {"openyoutube": "echo yt"},
            "requires": {"openyoutube": ["proxy"]},
            "sequences": {"news": {"steps": ["openyoutube"]}},
            "match": {"news": ["включи новости"]},
        })
        try:
            matcher = CommandMatcher(path, status_store=self._fake_store(set()))
            assert matcher.execute_by_id("news") is False
            run_mock.assert_not_called()
        finally:
            os.unlink(path)
