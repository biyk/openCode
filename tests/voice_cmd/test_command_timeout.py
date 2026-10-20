# TOOLTIP: Тесты потолка длительности shell-команды: зависший ребёнок не должен глушить микрофон
"""Тесты `CommandMatcher._run`: зависший дочерний процесс снимается по потолку.

Команда запускается синхронно в единственном цикле распознавания, поэтому
потерянная на минуту команда — это минута, когда ассистент ничего не слышит.
Проверяется, что `timeout` передан субпроцессу, а `TimeoutExpired` становится
обычным False: команда не считается выполненной, provides не выставляются,
статистика не пишется.
"""

import json
import os
import subprocess
import tempfile

from pathlib import Path

import pytest

from lib.core.tuning import COMMAND_TIMEOUT_S
from lib.skills import skill_actions
from lib.voice_cmd.commands import CommandMatcher

REPO_ROOT = Path(__file__).resolve().parents[2]
# Файлы, чьи шаги исполняются синхронно в цикле распознавания.
RUNTIME_FILES = ("lib/voice_cmd/commands.py", "lib/skills/skill_actions.py")
# Длина среза после `subprocess.run(`: вызов не переносится дальше.
CHUNK_TAIL = 250


def _write_cfg(cfg: dict) -> str:
    """Пишет конфиг устройства во временный файл, возвращает путь."""
    path = tempfile.mktemp(suffix=".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return path


def _cfg() -> dict:
    """Одна команда с provides-статусом: по нему видно, дошёл ли шаг до конца."""
    return {
        "triggers": ["алиса"],
        "commands": {"demo": {"default": "echo demo"}},
        "match": {"demo": ["демо"]},
        "provides": {"demo": ["demo_done"]},
    }


class TestCommandTimeout:
    """Потолок длительности и его последствия для статуса/статистики."""

    def test_timeout_passed_to_subprocess(self, mocker):
        """Субпроцесс запускается с потолком из tuning (не вечное ожидание)."""
        path = _write_cfg(_cfg())
        run = mocker.patch("lib.voice_cmd.commands.subprocess.run")
        try:
            matcher = CommandMatcher(path)
            assert matcher._run("echo demo", "demo") is True
            assert run.call_args.kwargs["timeout"] == COMMAND_TIMEOUT_S
        finally:
            os.unlink(path)

    def test_hang_is_failure_not_exception(self, mocker, capsys):
        """Нет ответа за потолок — False и строка в лог, цикл распознавания жив."""
        mocker.patch("lib.voice_cmd.commands.platform.system",
                     return_value="Linux")
        path = _write_cfg(_cfg())
        mocker.patch("lib.voice_cmd.commands.subprocess.run",
                     side_effect=subprocess.TimeoutExpired("echo demo", 1))
        try:
            matcher = CommandMatcher(path)
            assert matcher.execute_by_id("demo") is False
            assert "нет ответа за" in capsys.readouterr().out
        finally:
            os.unlink(path)

    def test_timeout_leaves_no_status_or_stats(self, mocker):
        """Снятая команда не помечает provides и не идёт в статистику."""
        mocker.patch("lib.voice_cmd.commands.platform.system",
                     return_value="Linux")
        path = _write_cfg(_cfg())
        mocker.patch("lib.voice_cmd.commands.subprocess.run",
                     side_effect=subprocess.TimeoutExpired("echo demo", 1))
        store = mocker.MagicMock()
        try:
            matcher = CommandMatcher(path, status_store=store)
            stats = mocker.patch.object(matcher._stats, "bump")
            assert matcher.execute_by_id("demo") is False
            stats.assert_not_called()
            store.set.assert_not_called()
        finally:
            os.unlink(path)


class TestSkillsCeiling:
    """Шаг скилла `run_cmd` ждётся тем же потолком: он тоже идёт в цикле STT."""

    def test_run_cmd_passes_timeout(self, mocker):
        run = mocker.patch("lib.skills.skill_actions.subprocess.run")
        skill_actions.SkillActionsMixin._action_run_cmd(
            mocker.MagicMock(), {"cmd": "echo demo"})
        assert run.call_args.kwargs["timeout"] == COMMAND_TIMEOUT_S


class TestCeilingIsKept:
    """Ни одного голого `subprocess.run(` в файлах цикла распознавания.

    Новый шаг, добавленный в обвязку команд без потолка, вернёт ровно тот же
    дефект: микрофон глохнет на всё время, пока ребёнок молчит. Мок здесь не
    поможет — его пишет тот, кто пишет шаг, поэтому проверяется текст.
    """

    @pytest.mark.parametrize("relative", RUNTIME_FILES)
    def test_no_bare_run(self, relative):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        chunks = source.split("subprocess.run(")[1:]
        assert chunks, f"{relative}: ни одного запуска не видно — страж слепнет"
        for chunk in chunks:
            assert "timeout=" in chunk[:CHUNK_TAIL], (
                f"{relative}: запуск без `timeout=` — зависший ребёнок "
                "оглушает микрофон")
