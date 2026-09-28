"""Ретрай event-match при сетевом сбое (SSLEOFError и прочие OSError)."""

from unittest.mock import MagicMock

from lib.core.orchestrator_event_match import OrchestratorEventMatchMixin

UUID = "abc12345-1234-1234-1234-123456789abc"
EVENT = {"summary": "Почистить зубы", "colorId": ""}


class _FakeOrchestrator(OrchestratorEventMatchMixin):
    def __init__(self):
        self._matcher = MagicMock()
        self._output = MagicMock()
        self._decision = None
        self._event_matcher = None

    def _execute_decision(self, cmd_id, text, forced_text=None):
        self._executed = (cmd_id, text, forced_text)
        return True


def _orch(finder):
    orch = _FakeOrchestrator()
    orch._matcher.core_phrase.return_value = "я почистил зубы"
    orch._event_matcher = finder
    return orch


def test_network_glitch_retried_once():
    finder = MagicMock()
    finder.find_task_event.side_effect = [OSError("SSLEOFError"), EVENT]
    finder.event_uuid.return_value = UUID
    orch = _orch(finder)
    assert orch._try_event_match("алиса я почистил зубы") is True
    assert finder.find_task_event.call_count == 2
    assert orch._executed[0] == "taskdone"


def test_second_failure_still_gives_up():
    finder = MagicMock()
    finder.find_task_event.side_effect = OSError("SSLEOFError")
    orch = _orch(finder)
    assert orch._try_event_match("алиса я почистил зубы") is False
    assert finder.find_task_event.call_count == 2
