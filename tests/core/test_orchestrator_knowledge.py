"""Сквозные тесты базы знаний в пайплайне оркестратора.

Проверяют: подтверждённая запись разрешает команду/мероприятие без LLM и
без нечёткого матчинга; распознанное Лайей падает в корзину laya; а
нераспознанное — в undefined. Алиас-путь упразднён — единый канал знаний.
"""

import json
from unittest.mock import MagicMock

from lib.core.orchestrator import Orchestrator
from lib.voice_cmd.knowledge import LAYA, UNDEFINED, KnowledgeStore


def _build(tmp_path, seed=None, core="дичь", needs_text=False, decision=None):
    kpath = str(tmp_path / "knowledge.json")
    if seed is not None:
        with open(kpath, "w", encoding="utf-8") as f:
            json.dump(seed, f, ensure_ascii=False)
    knowledge = KnowledgeStore(kpath)
    matcher = MagicMock()
    matcher.find_command.return_value = (None, [])
    matcher.has_trigger.return_value = True
    matcher.core_phrase.return_value = core
    matcher.missing_requires.return_value = []
    matcher.needs_text.return_value = needs_text
    matcher.execute_by_id.return_value = True
    matcher.match_config.return_value = {}
    orch = Orchestrator(matcher=matcher, output=MagicMock(),
                        tts=MagicMock(), knowledge=knowledge,
                        decision=decision)
    return orch, matcher, knowledge


class TestConfirmedResolution:
    def test_confirmed_command_bypasses_laya(self, tmp_path):
        orch, matcher, _ = _build(
            tmp_path, core="включи и ютюб",
            seed={"confirmed": {"включи и ютюб": {
                "kind": "command", "command": "openyoutube", "hits": 0}}})
        orch.process_text("алиса включи и ютюб")
        matcher.execute_by_id.assert_called_once_with("openyoutube")

    def test_confirmed_event_synonym_routes(self, tmp_path):
        orch, matcher, _ = _build(
            tmp_path, core="я витамины выпил", needs_text=True,
            seed={"confirmed": {"я витамины выпил": {
                "kind": "finish", "event": "Завтрак. Принять витамины",
                "hits": 0}}})
        orch._event_matcher = MagicMock()          # не должен понадобиться
        orch.process_text("алиса я витамины выпил")
        matcher.execute_by_id.assert_called_once_with(
            "taskdone", ("Завтрак. Принять витамины",))
        orch._event_matcher.find_task_event.assert_not_called()

    def test_confirmed_command_uses_curated_event(self, tmp_path):
        # ключ с доски (event) доходит до рантайма: {{text}} = event как есть,
        # а не перерезанная коверканная фраза с командными словами внутри
        orch, matcher, _ = _build(
            tmp_path, core="по стать задачу починить резинку", needs_text=True,
            seed={"confirmed": {"по стать задачу починить резинку": {
                "kind": "command", "command": "task-add",
                "event": "починить резинку", "hits": 0}}})
        matcher.match_config.return_value = {"task-add": ["поставь задачу"]}
        orch.process_text("алиса по стать задачу починить резинку")
        matcher.execute_by_id.assert_called_once_with(
            "task-add", ("починить резинку",))

    def test_laya_stays_unresolved(self, tmp_path):
        # laya-корзина НЕ участвует в рантайме — уходим в Лайю-детект
        decision = MagicMock()
        decision.detect.return_value = None
        orch, matcher, _ = _build(
            tmp_path, core="тише", decision=decision,
            seed={"laya": {"тише": {"kind": "command",
                                    "command": "volumedown", "hits": 0}}})
        orch._event_matcher = MagicMock()
        orch._event_matcher.find_task_event.return_value = None
        orch.process_text("алиса тише")
        decision.detect.assert_called_once()
        matcher.execute_by_id.assert_not_called()


class TestCapture:
    def test_laya_hit_recorded_as_laya(self, tmp_path):
        decision = MagicMock()
        decision.detect.return_value = ("volumeup", 0.95, 0.12)
        orch, _, knowledge = _build(tmp_path, core="делай громче",
                                    decision=decision)
        orch.process_text("алиса делай громче")
        assert knowledge.entries(LAYA)["делай громче"]["command"] == "volumeup"

    def test_unrecognized_recorded_as_undefined(self, tmp_path):
        decision = MagicMock()
        decision.detect.return_value = None
        orch, _, knowledge = _build(tmp_path, core="абракадабра",
                                    decision=decision)
        finder = MagicMock()
        finder.find_task_event.return_value = None
        orch._event_matcher = finder
        orch.process_text("алиса абракадабра")
        assert "абракадабра" in knowledge.entries(UNDEFINED)
