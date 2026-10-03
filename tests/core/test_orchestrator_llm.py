# tests/core/test_orchestrator_llm.py
"""LLM-детект команды после промаха Лайи: id + параметр вторым запросом."""

import threading
import time
from unittest.mock import MagicMock

from lib.core.orchestrator import Orchestrator
from lib.voice_cmd.knowledge import LAYA, UNDEFINED, KnowledgeStore


class _StubLLM:
    """classify: детект-промпт → id; промпт про параметр → подстрока фразы."""

    def __init__(self, detect, param=None, gate=None):
        self.detect = detect
        self.param = param
        self.gate = gate
        self.prompts = []

    def classify(self, prompt):
        self.prompts.append(prompt)
        if self.gate is not None:
            self.gate.wait(5)
        if "значением параметра" in prompt:
            return self.param
        return self.detect


def _build(tmp_path, llm, needs_text=True, missing=()):
    matcher = MagicMock()
    matcher.triggers = ("алиса",)
    matcher.has_trigger.side_effect = lambda t: any(
        w in t for w in matcher.triggers)
    matcher.find_command.return_value = (None, [])
    matcher.core_phrase.side_effect = lambda t: t.replace("алиса ", "").strip()
    matcher.match_config.return_value = {
        "task-add": ["поставь задачу", "добавь задачу"],
        "openyoutube": ["открой ютуб"]}
    matcher.sequences.return_value = {}
    matcher.needs_text.return_value = needs_text
    matcher.missing_requires.return_value = list(missing)
    matcher.execute_by_id.return_value = True
    matcher.status_snapshot.return_value = {}
    matcher.requires_map.return_value = {}
    matcher.need_message.side_effect = lambda n: f"нужен статус {n}"
    output = MagicMock()
    k = KnowledgeStore(str(tmp_path / "knowledge.json"))
    orch = Orchestrator(matcher=matcher, output=output, tts=MagicMock(),
                        knowledge=k, llm=llm)
    # Event-match (шаг перед LLM) глушим заглушкой: ищет он по реальному
    # календарю/таблице, а здесь проверяем именно LLM-детект команды.
    finder = MagicMock()
    finder.find_task_event.return_value = None
    orch._event_matcher = finder
    return orch, matcher, k


class TestRunLlmFallback:
    def test_composite_command_gets_param_from_second_request(self, tmp_path):
        # «поставь задачу {текст}»: первым запросом id, вторым — параметр;
        # execute идёт с extracted-параметром как {{text}}, не перерезая фразу
        llm = _StubLLM(detect="task-add", param="убраться на балконе")
        orch, matcher, k = _build(tmp_path, llm)
        assert orch._run_llm_fallback(
            "алиса по стать задачу убраться на балконе") is True
        matcher.execute_by_id.assert_called_once_with(
            "task-add", ("убраться на балконе",))
        # два запроса: детект + параметр
        assert len(llm.prompts) == 2
        # догадка легла в laya-корзину с командой и параметром
        e = k.entries(LAYA)["по стать задачу убраться на балконе"]
        assert e["command"] == "task-add"
        assert e["event"] == "убраться на балконе"

    def test_command_without_param_executes_bare(self, tmp_path):
        llm = _StubLLM(detect="openyoutube")
        orch, matcher, k = _build(tmp_path, llm, needs_text=False)
        assert orch._run_llm_fallback("алиса открой ютюб") is True
        matcher.execute_by_id.assert_called_once_with("openyoutube")
        assert llm.prompts and len(llm.prompts) == 1  # второй запрос не нужен

    def test_blocked_command_not_executed_but_remembered(self, tmp_path):
        llm = _StubLLM(detect="task-add", param="x")
        orch, matcher, k = _build(tmp_path, llm, missing=("google",))
        assert orch._run_llm_fallback("алиса поставь задачу x") is True
        matcher.execute_by_id.assert_not_called()
        assert "поставь задачу x" in k.entries(LAYA)

    def test_none_answer_not_handled(self, tmp_path):
        llm = _StubLLM(detect=None)  # classify вернул None → команды нет
        orch, matcher, k = _build(tmp_path, llm)
        assert orch._run_llm_fallback("алиса не знаю что") is False
        matcher.execute_by_id.assert_not_called()


class TestPipelineWiring:
    def test_llm_fallback_runs_after_laya_miss(self, tmp_path):
        # Лайя None → в шаг промаха встроен LLM-детект (в фоне, ждём воркер)
        llm = _StubLLM(detect="task-add", param="сделать хлеб")
        orch, matcher, k = _build(tmp_path, llm)
        decision = MagicMock()
        decision.detect.return_value = None
        orch._decision = decision
        orch.process_text("алиса же поставь задачу сделать хлеб")
        orch._llm_queue.join()
        matcher.execute_by_id.assert_called_once_with(
            "task-add", ("сделать хлеб",))

    def test_no_llm_falls_through_to_undefined(self, tmp_path):
        # без LLM (llm=None) промах Лайи по-прежнему уходит в undefined
        orch, matcher, k = _build(tmp_path, llm=None)
        decision = MagicMock()
        decision.detect.return_value = None
        decision.guess = None
        orch._decision = decision
        orch.process_text("алиса абракадабра")
        matcher.execute_by_id.assert_not_called()
        assert "абракадабра" in k.entries(UNDEFINED)


class TestLlmFallbackIsBackground:
    """Регресс бага 2026-10-02: минута гонки глушила цикл распознавания."""

    def _laya_miss(self, orch):
        decision = MagicMock()
        decision.detect.return_value = None
        orch._decision = decision

    def test_process_text_returns_while_race_is_slow(self, tmp_path):
        """Пока classify висит, process_text свободен — worker слышит дальше."""
        gate = threading.Event()
        llm = _StubLLM(detect="task-add", param="сделать хлеб", gate=gate)
        orch, matcher, k = _build(tmp_path, llm)
        self._laya_miss(orch)
        started = time.monotonic()
        orch.process_text("алиса поставь задачу сделать хлеб")
        elapsed = time.monotonic() - started
        gate.set()
        orch._llm_queue.join()
        assert elapsed < 1.0, f"ввод заблокирован на {elapsed:.1f}с"
        matcher.execute_by_id.assert_called_once_with(
            "task-add", ("сделать хлеб",))

    def test_stop_word_cancels_slow_fallback(self, tmp_path):
        """Стоп-слово во время гонки: запоздалая команда не исполнится."""
        gate = threading.Event()
        llm = _StubLLM(detect="task-add", param="x", gate=gate)
        orch, matcher, k = _build(tmp_path, llm)
        self._laya_miss(orch)
        orch.process_text("алиса поставь задачу x")
        for _ in range(100):
            if orch._llm_active:
                break
            time.sleep(0.02)
        assert orch._llm_pending()
        orch.process_text("стоп")
        gate.set()
        orch._llm_queue.join()
        matcher.execute_by_id.assert_not_called()

    def test_new_command_works_while_fallback_pending(self, tmp_path):
        """Детект в фоне не мешает обычной команде из commands.json."""
        gate = threading.Event()
        llm = _StubLLM(detect=None, gate=gate)
        orch, matcher, k = _build(tmp_path, llm)
        self._laya_miss(orch)
        orch.process_text("алиса поставь задачу x")
        matcher.find_command.return_value = ("playpause", [])
        matcher.missing_requires.return_value = []
        matcher.execute_by_id.return_value = True
        orch.process_text("алиса пауза")
        matcher.execute_by_id.assert_called_once_with("playpause")
        gate.set()
        orch._llm_queue.join()
