"""_execute_decision: карта синонимов уточняет параметр задач (taskstart/done).

Выученный с доски вариант («пальцами гимнастику») подставляется каноническим
заголовком («Пальцевая гимнастика») сильнее нечёткого матча. Не-задачные
команды и промах по synonyms идут как есть.
"""

import json
from unittest.mock import MagicMock

from lib.core.orchestrator import Orchestrator
from lib.voice_cmd.knowledge import KnowledgeStore


def _build(tmp_path, synonyms=None, needs_text=True):
    kpath = str(tmp_path / "knowledge.json")
    with open(kpath, "w", encoding="utf-8") as f:
        json.dump({"synonyms": synonyms or {}}, f, ensure_ascii=False)
    knowledge = KnowledgeStore(kpath)
    matcher = MagicMock()
    matcher.needs_text.return_value = needs_text
    matcher.execute_by_id.return_value = True
    orch = Orchestrator(matcher=matcher, output=MagicMock(),
                        tts=MagicMock(), knowledge=knowledge)
    return orch, matcher


class TestTaskSynonymSubstitution:
    def test_taskdone_hit_substitutes_canonical(self, tmp_path):
        orch, matcher = _build(
            tmp_path, {"пальцами гимнастику": "Пальцевая гимнастика"})
        assert orch._execute_decision(
            "taskdone", "закончил пальцами гимнастику",
            forced_text="пальцами гимнастику") is True
        matcher.execute_by_id.assert_called_once_with(
            "taskdone", ("Пальцевая гимнастика",))

    def test_taskstart_hit_substitutes_canonical(self, tmp_path):
        orch, matcher = _build(tmp_path, {"зарядку": "Утренняя зарядка"})
        orch._execute_decision("taskstart", "начал зарядку",
                               forced_text="зарядку")
        matcher.execute_by_id.assert_called_once_with(
            "taskstart", ("Утренняя зарядка",))

    def test_task_miss_keeps_fragment(self, tmp_path):
        orch, matcher = _build(tmp_path, {})
        orch._execute_decision("taskdone", "закончил чтение",
                               forced_text="чтение")
        matcher.execute_by_id.assert_called_once_with(
            "taskdone", ("чтение",))

    def test_non_task_command_not_substituted(self, tmp_path):
        orch, matcher = _build(
            tmp_path, {"дальше приготовить гречку": "Не подменять"})
        orch._execute_decision("task-add", "поставь задачу",
                               forced_text="дальше приготовить гречку")
        matcher.execute_by_id.assert_called_once_with(
            "task-add", ("дальше приготовить гречку",))

    def test_works_without_knowledge_store(self, tmp_path):
        matcher = MagicMock()
        matcher.needs_text.return_value = True
        matcher.execute_by_id.return_value = True
        orch = Orchestrator(matcher=matcher, output=MagicMock(),
                            tts=MagicMock(), knowledge=None)
        orch._execute_decision("taskdone", "закончил x", forced_text="x")
        matcher.execute_by_id.assert_called_once_with("taskdone", ("x",))
