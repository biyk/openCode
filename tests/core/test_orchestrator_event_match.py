"""Тесты миксина OrchestratorEventMatchMixin.

Проверяют: привязка нераспознанной речи к невыполненному мероприятию
дня (colorId != '7'), определение start/complete через Laya/эвристику.
"""

from unittest.mock import ANY, MagicMock

import pytest

from lib.core.orchestrator import Orchestrator
from lib.core.orchestrator_event_match import (
    OrchestratorEventMatchMixin, is_event_candidate, is_undone)


class _FakeOrchestrator(OrchestratorEventMatchMixin):
    """Минимальный оркестратор-заглушка для теста миксина."""

    def __init__(self):
        self._matcher = MagicMock()
        self._output = MagicMock()
        self._decision = None
        self._event_matcher = None

    def _execute_decision(self, cmd_id, text, forced_text=None):
        self._executed = (cmd_id, text, forced_text)
        return True


UUID = "abc12345-1234-1234-1234-123456789abc"


def _finder(event):
    finder = MagicMock()
    finder.find_task_event.return_value = event
    finder.event_uuid.return_value = UUID if event else None
    return finder


class TestIsUndone:
    def test_no_color(self):
        assert is_undone({"colorId": ""}) is True

    def test_done_color(self):
        assert is_undone({"colorId": "7"}) is False

    def test_other_color(self):
        assert is_undone({"colorId": "4"}) is True

    def test_missing_key(self):
        assert is_undone({}) is True


class TestTryEventMatch:
    def setup_method(self):
        self.orch = _FakeOrchestrator()
        self.orch._matcher.core_phrase.return_value = "я почистил зубы"

    def test_no_core_phrase(self):
        self.orch._matcher.core_phrase.return_value = ""
        assert self.orch._try_event_match("алиса") is False

    def test_candidate_filter_passed_to_finder(self):
        finder = _finder(None)
        self.orch._event_matcher = finder
        assert self.orch._try_event_match("алиса почистил зубы") is False
        finder.find_task_event.assert_called_once_with(
            "я почистил зубы", filter_fn=is_event_candidate, report=ANY)

    def test_event_without_uuid(self):
        event = {"summary": "Почистить зубы", "description": "",
                 "colorId": ""}
        finder = MagicMock()
        finder.find_task_event.return_value = event
        finder.event_uuid.return_value = None
        self.orch._event_matcher = finder
        assert self.orch._try_event_match("алиса почистил зубы") is False

    def test_match_complete_by_heuristic(self):
        event = {"summary": "Почистить зубы", "colorId": ""}
        self.orch._event_matcher = _finder(event)
        assert self.orch._try_event_match("алиса я почистил зубы") is True
        assert self.orch._executed[0] == "taskdone"
        # исполняем по чистому заголовку, а не по коверканной фразе
        assert self.orch._executed[2] == "Почистить зубы"

    def test_match_start_by_heuristic(self):
        event = {"summary": "Тренировка", "colorId": ""}
        self.orch._event_matcher = _finder(event)
        self.orch._matcher.core_phrase.return_value = "начинаю тренировку"
        assert self.orch._try_event_match("алиса начинаю тренировку") is True
        assert self.orch._executed[0] == "taskstart"

    def test_laya_overrides_heuristic(self):
        event = {"summary": "Почистить зубы", "colorId": ""}
        self.orch._event_matcher = _finder(event)
        self.orch._decision = MagicMock()
        self.orch._decision.detect.return_value = ("start", 0.7, 0.1)
        assert self.orch._try_event_match("алиса я почистил зубы") is True
        assert self.orch._executed[0] == "taskstart"

    def test_finder_raises_exception(self):
        finder = MagicMock()
        finder.find_task_event.side_effect = OSError("network")
        self.orch._event_matcher = finder
        assert self.orch._try_event_match("алиса почистил") is False


class TestDetectActionHeuristic:
    @pytest.mark.parametrize("text,expected", [
        ("я почистил зубы", "complete"),
        ("закончил уход за ногтями", "complete"),  # «закончил» = завершение
        ("нет грязной посуды", "complete"),   # совпало без глагола = закончил
        ("зубы", "complete"),                 # голое слово: было start, теперь complete
        ("начинаю тренировку", "start"),
        ("начал торговать на бирже", "start"),  # сов.вид «начал» = старт (регресс)
        ("пошёл чистить зубы", "start"),          # «пошёл делать» = старт (регресс)
        ("иду мыть посуду", "start"),
        ("сейчас буду уборку", "start"),
    ])
    def test_heuristic(self, text, expected):
        assert OrchestratorEventMatchMixin._detect_action_heuristic(
            text) == expected


class TestDetectEventActionWithLaya:
    def test_laya_returns_choice(self):
        orch = _FakeOrchestrator()
        orch._decision = MagicMock()
        orch._decision.detect.return_value = ("complete", 0.8, 0.05)
        assert orch._detect_event_action("я почистил зубы") == "complete"
        orch._decision.detect.assert_called_once()

    def test_laya_none_falls_to_heuristic(self):
        orch = _FakeOrchestrator()
        orch._decision = MagicMock()
        orch._decision.detect.return_value = None
        assert orch._detect_event_action("я почистил зубы") == "complete"

    def test_laya_exception_falls_to_heuristic(self):
        orch = _FakeOrchestrator()
        orch._decision = MagicMock()
        orch._decision.detect.side_effect = ConnectionError("dead")
        assert orch._detect_event_action("я почистил зубы") == "complete"


class TestIsSelfReport:
    """Различаем само-отчёт («я почистил зубы») и просьбу («открой ютуб»)."""

    @pytest.mark.parametrize("core,expected", [
        ("я почистил зубы", True),        # местоимение 1-го лица
        ("закончил зарядку", True),       # прошедшее время без «я»
        ("открой ютуб", False),           # императив — просьба
    ])
    def test_detects(self, core, expected):
        o = _FakeOrchestrator()
        o._matcher.core_phrase.return_value = core
        assert o._is_self_report("t") is expected

    def test_non_str_core_is_not_self_report(self):
        # core_phrase — MagicMock (не str): не падаем, не само-отчёт
        assert _FakeOrchestrator()._is_self_report("t") is False


class TestSelfReportBeatsLayaCommand:
    """Регресс: «алиса я почистил зубы» не запускает wakefix даже при ложном
    распознавании Лайи."""

    def _make(self, mocker):
        matcher = mocker.MagicMock()
        matcher.find_command.return_value = (None, [], False)
        matcher.has_trigger.return_value = True
        matcher.needs_text.return_value = False
        matcher.core_phrase.return_value = "я почистил зубы"
        matcher.execute_by_id.return_value = True

        decision = mocker.MagicMock()

        def detect(text, criteria=None, **kw):
            # вопрос «start/complete» от event-match vs распознавание команды
            if criteria is not None:
                return ("complete", 0.8, 0.05)
            return ("wakefix", 0.61, 0.40)

        decision.detect.side_effect = detect
        orch = Orchestrator(matcher=matcher, output=mocker.MagicMock(),
                            tts=mocker.MagicMock(), decision=decision)
        event = {"summary": "Почистить зубы утро", "colorId": "", "description": UUID}
        finder = mocker.MagicMock()
        finder.find_task_event.return_value = event
        finder.event_uuid.return_value = UUID
        orch._event_matcher = finder
        return orch, matcher

    def test_executes_taskdone_not_wakefix(self, mocker):
        orch, matcher = self._make(mocker)
        orch.process_text("алиса я почистил зубы")
        executed = [c.args[0] for c in matcher.execute_by_id.call_args_list]
        assert "wakefix" not in executed
        assert "taskdone" in executed
