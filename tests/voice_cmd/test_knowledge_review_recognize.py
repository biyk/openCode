"""Тесты распознавания фразы для доски: разбор ответа LLM и Laya→LLM."""

import json

import pytest

from lib.voice_cmd import knowledge_review_recognize as kr
from lib.voice_cmd.knowledge_review_recognize import try_recognize


@pytest.fixture
def cfile(tmp_path):
    """Временный commands.json (команды, match-шаблоны, пустой decision)."""
    data = {"commands": {"stop": "cmd", "volumedown": "cmd2"},
            "descriptions": {"stop": "остановить медиа"},
            "match": {"stop": ["стоп музыка"]},
            "decision": {"enabled": False}}
    path = tmp_path / "commands.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


class TestRecognize:
    def test_parse_llm_plain_json(self):
        got = kr._parse_llm('{"kind":"finish","event":"Завтрак"}', ["stop"])
        assert got == {"kind": "finish", "command": "", "event": "Завтрак"}

    def test_parse_llm_json_in_prose(self):
        got = kr._parse_llm('Думаю... {"kind":"command","command":"stop"}',
                            ["stop"])
        assert got["kind"] == "command" and got["command"] == "stop"

    def test_parse_llm_rejects_unknown_command(self):
        assert kr._parse_llm('{"kind":"command","command":"нет"}',
                             ["stop"]) is None

    def test_parse_llm_rejects_eventless_finish(self):
        assert kr._parse_llm('{"kind":"finish"}', ["stop"]) is None

    def test_laya_answer_wins(self, monkeypatch):
        monkeypatch.setattr(kr, "laya_guess", lambda t, c: "volumedown")
        assert try_recognize("тише", "x", {}) == {
            "via": "laya", "kind": "command", "command": "volumedown",
            "event": ""}

    def test_llm_fallback(self, monkeypatch, cfile):
        monkeypatch.setattr(kr, "laya_guess", lambda t, c: None)

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {
                    "content": '{"kind":"command","command":"stop"}'}}]}

        monkeypatch.setattr(kr.requests, "post", lambda *a, **k: _Resp())
        got = try_recognize("стоп музыка", cfile,
                            {"llm_url": "http://l/v1"})
        assert got["via"] == "llm" and got["command"] == "stop"

    def test_none_when_all_fail(self, monkeypatch, cfile):
        monkeypatch.setattr(kr, "laya_guess", lambda t, c: None)
        monkeypatch.setattr(kr, "llm_guess", lambda *a: None)
        assert try_recognize("ы ы ы", cfile, {})["via"] == "none"
