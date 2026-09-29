"""Тесты Orchestrator: авто-кандидат недословной фразы → laya-корзина знаний."""

from unittest.mock import MagicMock

from lib.core.orchestrator import Orchestrator
from lib.voice_cmd.knowledge import LAYA, KnowledgeStore


def _build(tmp_path, core, decision, find=(None, []),
           missing=None):
    """Оркестратор с настоящим KnowledgeStore и моками matcher/decision."""
    knowledge = KnowledgeStore(str(tmp_path / "knowledge.json"))
    matcher = MagicMock()
    matcher.find_command.return_value = find
    matcher.has_trigger.return_value = True
    matcher.core_phrase.return_value = core
    matcher.missing_requires.return_value = missing or []
    matcher.needs_text.return_value = False
    matcher.execute_by_id.return_value = True
    matcher.match_config.return_value = {}
    orch = Orchestrator(matcher=matcher, output=MagicMock(),
                        tts=MagicMock(), knowledge=knowledge,
                        decision=decision)
    return orch, knowledge


class TestRememberCandidate:
    """Единый канал: недословный кандидат Лайи → laya на досмотр."""

    def test_garbled_laya_hit_recorded_in_laya(self, tmp_path):
        """commands.json не сматчил, Лайя распознала → laya-корзина."""
        decision = MagicMock()
        decision.detect.return_value = ("volumeup", 0.95, 0.12)
        orch, knowledge = _build(tmp_path, "делай громче", decision)
        orch.process_text("алиса делай громче")
        assert knowledge.entries(LAYA)["делай громче"]["command"] == "volumeup"

    def test_literal_command_not_recorded(self, tmp_path):
        """Дословная команда (даже заблокированная) не идёт в laya."""
        decision = MagicMock()
        decision.detect.return_value = ("openyoutube", 0.9, 0.1)
        orch, knowledge = _build(
            tmp_path, "открой ютюб", decision,
            find=("openyoutube", []), missing=["proxy"])
        orch.process_text("алиса открой ютюб")
        assert knowledge.entries(LAYA) == {}
