"""Засечка длительности команды в CommandMatcher (lib/voice_cmd/commands.py).

Команду исполняет дочерний процесс: пока он делает Google-запросы, в консоли
не было ни одной строки. `_run` печатает длительность шага всегда — и на
успехе, и на провале.
"""
import json
import subprocess

import pytest

from lib.core import timing
from lib.voice_cmd.commands import CommandMatcher


@pytest.fixture(autouse=True)
def _quiet_timing(monkeypatch, tmp_path):
    monkeypatch.setattr(timing, "LOG_FILE", str(tmp_path / "timing.log"))
    monkeypatch.delenv(timing.ENV_SWITCH, raising=False)
    timing.disable()
    yield
    timing.disable()


@pytest.fixture
def commands_file(tmp_path):
    path = tmp_path / "commands.json"
    path.write_text(json.dumps({
        "commands": {"taskdone": "python -m lib.task_complete"},
        "match": {"taskdone": ["завершил"]},
    }, ensure_ascii=False), encoding="utf-8")
    return str(path)


class TestRunDurationReported:
    """Выполненная и сорвавшаяся команда — обе с засечкой."""

    def test_success_reports(self, commands_file, mocker, capsys):
        mocker.patch("lib.voice_cmd.commands.subprocess.run")
        assert CommandMatcher(commands_file).execute_by_id("taskdone") is True
        assert "команда taskdone за" in capsys.readouterr().out

    def test_failure_reports_too(self, commands_file, mocker, capsys):
        run = mocker.patch("lib.voice_cmd.commands.subprocess.run")
        run.side_effect = subprocess.CalledProcessError(1, "cmd")
        assert CommandMatcher(commands_file).execute_by_id("taskdone") is False
        assert "команда taskdone за" in capsys.readouterr().out

    def test_step_of_sequence_by_own_id(self, commands_file, mocker, capsys):
        """Составная команда: шаг подписывается своим id, а не shell-строкой."""
        path = commands_file
        data = json.loads(open(path, encoding="utf-8").read())
        data["sequences"] = {"morning": {"steps": ["taskdone"]}}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        mocker.patch("lib.voice_cmd.commands.subprocess.run")
        assert CommandMatcher(path).execute_by_id("morning") is True
        out = capsys.readouterr().out
        assert "команда taskdone за" in out
        assert "python -m lib.task_complete" not in out

    def test_written_to_log(self, commands_file, mocker):
        mocker.patch("lib.voice_cmd.commands.subprocess.run")
        CommandMatcher(commands_file).execute_by_id("taskdone")
        with open(timing.LOG_FILE, encoding="utf-8") as f:
            assert "команда taskdone" in f.read()
