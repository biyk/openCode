"""Юнит-тесты lib.taskflow.tasks_dedup.find_duplicate (exact → Laya → None)."""

from lib.taskflow.tasks_dedup import (
    BATCH_OPTS, BATCH_THRESHOLD, DUP_INSTRUCTIONS, DUP_THRESHOLD,
    MAX_EXISTING, MAX_OPTS, NONE_DESCRIPTION, PAIR_INSTRUCTIONS, PAIR_NONE,
    find_duplicate)


class FakeDecision:
    """Заглушка LayaDecision: вердикты по порядку, последний — навсегда."""

    def __init__(self, *verdicts):
        self._verdicts = list(verdicts) or [None]
        self.calls = []

    def detect(self, text, criteria=None, instructions=None, threshold=None):
        self.calls.append({"text": text, "criteria": criteria,
                           "instructions": instructions,
                           "threshold": threshold})
        if len(self._verdicts) > 1:
            return self._verdicts.pop(0)
        return self._verdicts[0]


def _boom():
    raise AssertionError("get_decision не должен вызываться")


class TestExact:
    def test_exact_normalizes_case_and_spaces(self):
        existing = [{"id": "1", "title": "Купить   Хлеб"}]
        hit = find_duplicate("купить хлеб", existing, _boom)
        assert hit == {"id": "1", "title": "Купить   Хлеб",
                       "method": "exact"}

    def test_empty_title_returns_none(self):
        assert find_duplicate("  ", [{"id": "1", "title": "хлеб"}], _boom)\
            is None

    def test_empty_list_skips_factory(self):
        assert find_duplicate("хлеб", [], _boom) is None


class TestLaya:
    def test_laya_hit_by_title_key_then_confirm(self):
        existing = [{"id": "a", "title": "помыть полы"},
                    {"id": "b", "title": "полить цветы"}]
        v = ("помыть полы", 0.9, 0.1)
        d = FakeDecision(v, v)
        hit = find_duplicate("вымыть пол", existing, lambda: d)
        assert hit == {"id": "a", "title": "помыть полы",
                       "method": "laya", "score": 0.9}
        batch, pair = d.calls
        assert batch["criteria"] == {
            "помыть полы": "открытая задача: помыть полы",
            "полить цветы": "открытая задача: полить цветы",
            "none": NONE_DESCRIPTION}
        assert batch["instructions"] == DUP_INSTRUCTIONS
        assert batch["threshold"] == BATCH_THRESHOLD
        assert "вымыть пол" in batch["text"]
        assert pair["criteria"] == {
            "помыть полы": "открытая задача: помыть полы",
            "none": PAIR_NONE}
        assert pair["instructions"] == PAIR_INSTRUCTIONS
        # Порог применяет вызывающий, чтобы видеть c и при отказе.
        assert pair["threshold"] == 0.0

    def test_laya_none_or_miss(self):
        # none (дубликата нет) или низкая уверенность — detect() отдаёт None
        d = FakeDecision(None)
        assert find_duplicate("хлеб", [{"id": "a", "title": "полы"}],
                              lambda: d) is None
        assert len(d.calls) == 1

    def test_confirm_rejects_candidate(self):
        d = FakeDecision(("полы", 0.9, 0.1), None)
        assert find_duplicate("хлеб", [{"id": "a", "title": "полы"}],
                              lambda: d) is None
        assert len(d.calls) == 2

    def test_confirm_other_choice_rejects(self):
        d = FakeDecision(("полы", 0.9, 0.1), ("хлеб", 0.9, 0.1))
        assert find_duplicate("хлеб", [{"id": "a", "title": "полы"}],
                              lambda: d) is None

    def test_no_client_returns_none(self):
        assert find_duplicate("хлеб", [{"id": "a", "title": "полы"}],
                              lambda: None) is None

    def test_get_decision_none_skips_laya(self):
        assert find_duplicate("хлеб", [{"id": "a", "title": "полы"}]) is None

    def test_unknown_choice_returns_none(self):
        for verdict in (("задача из другой пачки", 0.9, 0.1), ("", 0.9, 0.1)):
            d = FakeDecision(verdict)
            assert find_duplicate("хлеб", [{"id": "a", "title": "полы"}],
                                  lambda d=d: d) is None
            assert len(d.calls) == 1

    def test_error_in_first_batch_continues(self):
        existing = [{"id": "a", "title": "полы"},
                    {"id": "b", "title": "цветы"}]
        d = FakeDecision(None, ("полы", 0.8, 0.1))
        hit = find_duplicate("хлеб", existing, lambda: d)
        # одна пачка -> вопрос пачки сорвался, confirm не спрашиваем
        assert hit is None
        assert len(d.calls) == 1

    def test_options_batched_under_server_limit(self):
        existing = [{"id": str(i), "title": f"задача {i}"}
                    for i in range(MAX_EXISTING + 5)]
        n_batches = -(-MAX_EXISTING // BATCH_OPTS)
        verdict = (f"задача {MAX_EXISTING - 1}", 0.9, 0.1)
        d = FakeDecision(*([None] * (n_batches - 1)), verdict, verdict)
        hit = find_duplicate("новая", existing, lambda: d)
        assert hit["title"] == f"задача {MAX_EXISTING - 1}"
        for call in d.calls:
            assert len(call["criteria"]) <= MAX_OPTS
        assert len(d.calls) == n_batches + 1

    def test_titleless_tasks_excluded_from_options(self):
        existing = [{"id": "x"}, {"id": "a", "title": "полы"}]
        v = ("полы", 0.9, 0.1)
        d = FakeDecision(v, v)
        hit = find_duplicate("вымыть пол", existing, lambda: d)
        assert hit["method"] == "laya"
        assert d.calls[0]["criteria"]["полы"] == "открытая задача: полы"

    def test_hit_in_second_batch(self):
        existing = [{"id": str(i), "title": f"задача {i}"}
                    for i in range(BATCH_OPTS + 2)]
        verdict = (f"задача {BATCH_OPTS + 1}", 0.95, 0.1)
        d = FakeDecision(None, verdict, verdict)
        hit = find_duplicate("новая", existing, lambda: d)
        assert hit["title"] == f"задача {BATCH_OPTS + 1}"
        assert len(d.calls) == 3

    def test_confirm_low_confidence_not_duplicate(self):
        # Правило пользователя: c < DUP_THRESHOLD — не дубликат.
        v = ("полы", DUP_THRESHOLD - 0.3, 0.1)
        d = FakeDecision(v, v)
        assert find_duplicate("хлеб", [{"id": "a", "title": "полы"}],
                              lambda: d) is None

    def test_report_logs_rejected_score(self):
        msgs: list = []
        v = ("полы", DUP_THRESHOLD - 0.3, 0.1)
        d = FakeDecision(v, v)
        find_duplicate("хлеб", [{"id": "a", "title": "полы"}], lambda: d,
                       report=msgs.append)
        text = "\n".join(msgs)
        assert "кандидат «полы»" in text
        assert f"c={v[1]:.4f}" in text and "не дубликат" in text


class TestReport:
    def test_hit_without_id_gets_empty_string(self):
        v = ("полы", 0.9, 0.1)
        d = FakeDecision(v, v)
        hit = find_duplicate("пол", [{"title": "полы"}], lambda: d)
        assert hit == {"id": "", "title": "полы", "method": "laya",
                       "score": 0.9}
