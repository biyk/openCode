"""Сквозная цепочка: дефектное распознавание → commands.json → Laya.

STT искажает «ютуб» («я туб», «я ту», «я тут»): уровень commands.json
проваливается, decision-слой (мок Laya) получает ровно эту фразу и
возвращает правильную команду, оркестратор её выполняет.
"""
from __future__ import annotations

import platform

import pytest

from lib.voice_cmd.commands import CommandMatcher
from lib.voice_cmd.config_loader import get_device_commands_path
from lib.core.orchestrator import Orchestrator


@pytest.fixture
def matcher() -> CommandMatcher:
    """Матчер с реальным commands.json текущего устройства."""
    return CommandMatcher(get_device_commands_path(platform.node()))


class TestDecisionChainWithDefectiveSpeech:
    """commands.json пасует → Laya (мок) даёт правильную команду."""

    @pytest.mark.parametrize("phrase,expected", [
        ("алиса открой я туб", "openyoutube"),
        ("алиса открой я ту", "openyoutube"),
        ("алиса открой я тут", "openyoutube"),
    ])
    def test_commands_fails_then_laya_returns_right_command(
            self, matcher, mocker, phrase, expected):
        """commands.json не находит команду, Laya даёт правильную."""
        cmd_id, _settings, wait = matcher.find_command([phrase])
        assert cmd_id is None, (
            f"{phrase}: commands.json не должен находить команду, "
            f"найдена {cmd_id}"
        )
        assert not wait

        decision = mocker.MagicMock()
        decision.detect.return_value = (expected, 0.99, 0.25)
        mocker.patch.object(matcher, "execute_by_id", return_value=True)
        orch = Orchestrator(
            matcher=matcher,
            output=mocker.MagicMock(),
            tts=mocker.MagicMock(),
            decision=decision,
        )
        orch.process_text(phrase)

        decision.detect.assert_called_once_with(phrase)
        matcher.execute_by_id.assert_called_once_with(expected)
        orch._output.print_info.assert_any_call(
            f"[Decision] Лайя: команда распознана «{expected}» "
            f"(c=0.99 t=0.250)")
        orch._opencode_queue.empty()

    def test_clean_phrase_matches_at_level_one(self, matcher):
        """Нормальная «открой ютуб» ловится commands.json без Laya."""
        cmd_id, _settings, wait = matcher.find_command(
            ["алиса открой ютуб"])
        assert cmd_id == "openyoutube"
        assert not wait

    def test_laya_command_gets_phrase_as_text(self, matcher, mocker):
        """Laya дала {{text}}-команду — ядро фразы уходит ей как текст."""
        assert matcher.needs_text("taskstart") is True
        assert matcher.needs_text("openyoutube") is False
        decision = mocker.MagicMock()
        decision.detect.return_value = ("taskstart", 0.89, 0.4)
        mocker.patch.object(matcher, "execute_by_id", return_value=True)
        orch = Orchestrator(matcher=matcher, output=mocker.MagicMock(),
                            tts=mocker.MagicMock(), decision=decision)
        orch.process_text("алиса поставь приготовить гречку")
        matcher.execute_by_id.assert_called_once_with(
            "taskstart", ("поставь", "приготовить", "гречку"))

    def test_laya_task_add_strips_trigger_words(self, matcher, mocker):
        """Для task-add ведущие командные слова срезаются из текста."""
        decision = mocker.MagicMock()
        decision.detect.return_value = ("task-add", 0.9, 0.4)
        mocker.patch.object(matcher, "execute_by_id", return_value=True)
        orch = Orchestrator(matcher=matcher, output=mocker.MagicMock(),
                            tts=mocker.MagicMock(), decision=decision)
        orch.process_text("алиса поставь дальше приготовить гречку")
        matcher.execute_by_id.assert_called_once_with(
            "task-add", ("дальше", "приготовить", "гречку"))
