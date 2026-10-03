"""Тесты config-модуля доски: review.json, метаданные commands.json, разбор
ответа LLM. Фазы распознавания — test_knowledge_review_detect, уровни —
test_knowledge_review_levels."""

import json

import pytest

from lib.voice_cmd import knowledge_review_recognize as kr


@pytest.fixture
def cfile(tmp_path):
    """Временный commands.json (команды, match-шаблоны, пустой decision)."""
    data = {"commands": {"stop": "cmd", "volumedown": "cmd2",
                         "chat": "python -m x {{text}}"},
            "sequences": {"news": {"steps": ["stop"]}},
            "descriptions": {"stop": "остановить медиа"},
            "match": {"stop": ["стоп музыка"]},
            "decision": {"enabled": False,
                         "criteria": {"stop": "остановить медиа",
                                      "none": "не команда"}}}
    path = tmp_path / "commands.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


class TestCommandsMeta:
    def test_ids_include_sequences(self, cfile):
        ids, criteria = kr.commands_meta(kr.commands_data(cfile))
        assert set(ids) == {"stop", "volumedown", "chat", "news"}
        # criteria — как в конфиге: Лайе нужен и `none` как альтернатива
        assert criteria["stop"] == "остановить медиа"
        assert criteria["none"] == "не команда"

    def test_missing_file_is_empty(self, tmp_path):
        assert kr.commands_data(str(tmp_path / "nope.json")) == {}

    def test_free_text_ids(self, cfile):
        assert kr.free_text_ids(kr.commands_data(cfile)) == ["chat"]

    def test_questions_carry_phrase_and_command(self, cfile):
        _, criteria = kr.commands_meta(kr.commands_data(cfile))
        q = kr.llm_question("стоп музыка", criteria)
        assert "Фраза: стоп музыка" in q and "- stop —" in q
        assert "none" not in q
        p = kr.param_question("закончил гимнастику", "taskdone", criteria)
        assert "taskdone" in p and "закончил гимнастику" in p


class TestParseLlm:
    def test_plain_json(self):
        got = kr.parse_llm('{"kind":"finish","event":"Завтрак"}', ["stop"])
        assert got == {"kind": "finish", "command": "", "event": "Завтрак"}

    def test_json_in_prose(self):
        got = kr.parse_llm('Думаю... {"kind":"command","command":"stop"}',
                           ["stop"])
        assert got["kind"] == "command" and got["command"] == "stop"

    def test_rejects_unknown_command(self):
        assert kr.parse_llm('{"kind":"command","command":"нет"}',
                            ["stop"]) is None

    def test_rejects_eventless_finish(self):
        assert kr.parse_llm('{"kind":"finish"}', ["stop"]) is None

    def test_kind_none_kept(self):
        assert kr.parse_llm('{"kind":"none"}', ["stop"]) == {
            "kind": "none", "command": "", "event": ""}

    def test_garbage_answer(self):
        assert kr.parse_llm("извини, не понял", ["stop"]) is None
        assert kr.parse_llm("", ["stop"]) is None
