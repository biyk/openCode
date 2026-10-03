"""Тесты уровней распознавания доски (knowledge_review_levels).

Главное, что проверяется: вердикт Лайи виден в логе ДАЖЕ когда он не принят
по порогу (для этого `detect` вызывают с `on_verdict`), а LLM-уровень идёт
через активный провайдер (race omni+lmstudio) с фолбэком на прямой endpoint
из review.json.
"""

import json

import pytest

from lib.voice_cmd import knowledge_review_levels as lv


class _Dec:
    """Фейковая LayaDecision: вердикт вызывается до отбрасывания по порогу."""

    def __init__(self, hit=None, raises=False):
        self.hit, self.raises, self.kw = hit, raises, {}

    def detect(self, text, **kw):
        self.kw = kw
        on = kw.get("on_verdict")
        if on:
            on(self.hit[0] if self.hit else "none",
               self.hit[1] if self.hit else 0.0)
        if self.raises:
            raise RuntimeError("laya died")
        return self.hit if self.hit and self.hit[1] >= kw["threshold"] else None


@pytest.fixture
def cfile(tmp_path):
    data = {"commands": {"stop": "cmd"}, "decision": {"enabled": False}}
    path = tmp_path / "commands.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _with_laya(monkeypatch, decision):
    """Подменяет сборку клиента Лайи: вопрос идёт в фейк, сети нет."""
    monkeypatch.setattr(lv, "_laya",
                        lambda cf: (decision, lv.DECISION_THRESHOLD, "ok"))


class TestLayaVerdict:
    def test_hit_reports_state_and_confidence(self, monkeypatch):
        dec = _Dec(hit=("volumedown", 0.93))
        _with_laya(monkeypatch, dec)
        got = lv.laya_verdict("тише", "c")
        assert got == {"command": "volumedown", "confidence": 0.93,
                       "threshold": lv.DECISION_THRESHOLD, "state": "hit"}

    def test_below_threshold_keeps_number_as_miss(self, monkeypatch):
        # ради журнала: 0.64 не принято, но уровень обязан показать цифру
        _with_laya(monkeypatch, _Dec(hit=("volumedown", 0.64)))
        got = lv.laya_verdict("тише", "c")
        assert got["state"] == "miss" and got["confidence"] == 0.64

    def test_none_choice_is_not_a_miss(self, monkeypatch):
        _with_laya(monkeypatch, _Dec(hit=None))
        assert lv.laya_verdict("ы ы", "c")["state"] == "none"

    def test_detect_crash_is_state_error(self, monkeypatch):
        _with_laya(monkeypatch, _Dec(hit=("stop", 0.5), raises=True))
        assert lv.laya_verdict("стоп", "c")["state"] == "error"

    def test_disabled_laya_no_request(self, cfile):
        got = lv.laya_verdict("тише", cfile)
        assert got["state"] == "off" and got["command"] == ""

    def test_unreachable_server_is_down(self, monkeypatch, cfile):
        import lib.core.laya_decision as ld

        class _Dead:
            available = False

        monkeypatch.setattr(ld, "LayaDecision", lambda cfg: _Dead())
        monkeypatch.setattr(lv, "laya_config",
                            lambda cf: {"enabled": True, "url": "http://x"})
        assert lv.laya_verdict("тише", cfile)["state"] == "down"

    def test_bad_config_is_off(self, monkeypatch, cfile):
        import lib.core.laya_decision as ld

        def _boom(cfg):
            raise ValueError("no url")

        monkeypatch.setattr(ld, "LayaDecision", _boom)
        monkeypatch.setattr(lv, "laya_config",
                            lambda cf: {"enabled": True, "url": "http://x"})
        assert lv.laya_verdict("тише", cfile)["state"] == "off"

    def test_guess_contract_for_scanner(self, monkeypatch):
        _with_laya(monkeypatch, _Dec(hit=None))
        assert lv.laya_guess("ы ы", "c") is None


class TestLayaTitle:
    def test_asks_about_tasks_with_title_threshold(self, monkeypatch):
        dec = _Dec(hit=("Пальцевая гимнастика", 0.6))
        _with_laya(monkeypatch, dec)
        got = lv.laya_title("закончил пальцами", ["Пальцевая гимнастика"], "c")
        assert got["state"] == "miss" and got["threshold"] == lv.TITLE_THRESHOLD
        assert dec.kw["criteria"] == {"Пальцевая гимнастика": "задача из списка"}
        assert "какую из задач" in dec.kw["instructions"].lower()

    def test_empty_titles_skipped(self, monkeypatch, cfile):
        _with_laya(monkeypatch, _Dec())
        assert lv.laya_title("что-то", [], cfile)["state"] == "empty"


class TestLlmLevel:
    class _Race:
        name = "race"

        def __init__(self, answer="стоп", boom=False):
            self.answer, self.boom, self.prompt = answer, boom, ""

        def classify(self, prompt, timeout=None):
            self.prompt = prompt
            if self.boom:
                raise RuntimeError("race silent")
            return self.answer

    def test_race_answer_wins(self, monkeypatch):
        race = self._Race('{"kind":"command","command":"stop"}')
        monkeypatch.setattr(lv, "_client", lambda t=None: race)
        got, label = lv.llm_json("стоп музыка", ["stop"], {}, {})
        assert label == "LLM race" and got["command"] == "stop"
        assert "Фраза: стоп музыка" in race.prompt

    def test_falls_back_to_direct_endpoint(self, monkeypatch):
        seen = {}

        def direct(prompt, review):
            seen["prompt"] = prompt
            return "прямой ответ", "LLM http://d/v1"

        monkeypatch.setattr(lv, "_client", lambda t=None: self._Race(boom=True))
        monkeypatch.setattr(lv, "_direct", direct)
        got, label = lv.llm_ask("вопрос", {"llm_url": "http://d/v1"})
        assert (got, label) == ("прямой ответ", "LLM http://d/v1")
        assert seen["prompt"] == "вопрос"

    def test_direct_without_url_returns_none(self):
        assert lv._direct("q", {"llm_url": ""}) == (None, "LLM не настроен")

    def test_level_label_names_active_provider(self, monkeypatch):
        monkeypatch.setattr(lv, "_client", lambda t=None: self._Race())
        assert lv.llm_level({}) == "LLM race"
        monkeypatch.setattr(lv, "_client", lambda t=None: None)
        assert lv.llm_level({"llm_url": "http://d/v1"}) == "LLM http://d/v1"

    def test_param_answer_cleaned(self, monkeypatch):
        race = self._Race("«Пальцевая гимнастика»\nлишнее")
        monkeypatch.setattr(lv, "_client", lambda t=None: race)
        got, label = lv.llm_param("закончил пальцами", "taskdone", {}, {})
        assert got == "Пальцевая гимнастика" and label == "LLM race"
        assert "taskdone" in race.prompt

    def test_param_none_is_empty(self, monkeypatch):
        monkeypatch.setattr(lv, "_client", lambda t=None: self._Race("NONE"))
        assert lv.llm_param("закончил", "taskdone", {}, {})[0] == ""
        monkeypatch.setattr(lv, "_client", lambda t=None: None)
        assert lv.llm_param("закончил", "taskdone", {}, {"llm_url": ""})[0] == ""

    def test_no_provider_no_crash(self, monkeypatch):
        monkeypatch.setattr(lv, "_client", lambda t=None: None)
        assert lv.llm_json("ы", ["stop"], {}, {"llm_url": ""}) == (
            None, "LLM не настроен")
