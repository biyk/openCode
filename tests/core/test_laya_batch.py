"""Юнит-тесты батчинга Лайи: разбор критериев и агрегация вердиктов.

Транспорт (run_query) мокнется на уровне urllib.request.urlopen модуля
laya_batch; сетью не пользуемся.
"""

import json

from lib.core.laya_batch import (
    BATCH_OPTS, MAX_OPTS, plan_batches, query_batches, run_query,
)
from lib.core.laya_decision import LayaDecision


class FakeResponse:
    """Файлоподобный ответ urllib с контекст-менеджером (status=200 для health)."""

    def __init__(self, payload=None):
        self._payload = payload
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class TestPlanBatches:
    def test_fits_in_one_batch(self):
        """Ключей не больше ёмкости — один батч как есть."""
        assert plan_batches(["a", "b", "c"], capacity=15) == [["a", "b", "c"]]

    def test_empty(self):
        """Пустой список — пусто."""
        assert plan_batches([], capacity=15) == []

    def test_splits_roughly_equal(self):
        """16 ключей при ёмкости 15 → два примерно равных батча, не 15+1."""
        groups = plan_batches(list(range(16)), capacity=BATCH_OPTS)
        assert len(groups) == 2
        assert all(len(g) <= BATCH_OPTS for g in groups)
        assert sorted(len(g) for g in groups) == [8, 8]

    def test_none_exceeding_capacity(self):
        """Каждый ключ ровно в одном батче, порядок сохранён."""
        keys = [f"k{i}" for i in range(31)]
        groups = plan_batches(keys, capacity=BATCH_OPTS)
        assert [k for g in groups for k in g] == keys
        assert all(len(g) <= BATCH_OPTS for g in groups)


class TestQueryBatches:
    def test_single_when_fits(self):
        """Критериев ≤ MAX_OPTS — один запрос без разбиения."""
        calls = []

        def single(crit):
            calls.append(crit)
            return ("a", 0.9, 0.1)

        crit = {f"c{i}": "" for i in range(MAX_OPTS - 1)}
        crit["none"] = ""
        assert query_batches(crit, single) == ("a", 0.9, 0.1)
        assert len(calls) == 1

    def test_batches_and_picks_best_confidence(self):
        """Много критериев — батчи; берётся вердикт с макс. уверенностью."""
        seen_sizes = []

        def single(crit):
            # none всегда с нами, вариантов не больше лимита
            assert len(crit) <= MAX_OPTS
            assert "none" in crit
            seen_sizes.append(len(crit) - 1)
            if "c15" in crit:
                return ("c15", 0.85, 0.05)
            return None

        crit = {f"c{i}": "" for i in range(16)}
        crit["none"] = ""
        res = query_batches(crit, single)
        assert res[0] == "c15" and abs(res[1] - 0.85) < 1e-9
        assert all(n <= BATCH_OPTS for n in seen_sizes)

    def test_elapsed_sums_over_batches(self):
        """Время — сумма по всем батчам."""
        def single(crit):
            return ("x", 0.6, 0.1)

        crit = {f"c{i}": "" for i in range(16)}
        crit["none"] = ""
        res = query_batches(crit, single)
        assert res[2] > 0.1  # минимум два батча → сумма больше одного


class TestRunQuery:
    def _patch(self, mocker, answer):
        mocker.patch("lib.core.laya_batch.urllib.request.urlopen",
                     return_value=FakeResponse({"answers": {"command": answer}}))

    def test_returns_choice_above_threshold(self, mocker):
        self._patch(mocker, {"choice": "volumeup", "confidence": 0.9})
        res = run_query("http://x", 5, "инстр", "текст",
                        {"volumeup": "", "none": ""}, limit=0.5)
        assert res[0] == "volumeup" and res[2] >= 0.0

    def test_none_choice_returns_none(self, mocker):
        self._patch(mocker, {"choice": "none", "confidence": 0.9})
        seen = []
        res = run_query("http://x", 5, "инстр", "текст",
                        {"a": "", "none": ""}, limit=0.5,
                        on_verdict=lambda c, s: seen.append(c))
        assert res is None and seen == ["none"]

    def test_below_threshold_returns_none(self, mocker):
        self._patch(mocker, {"choice": "a", "confidence": 0.1})
        assert run_query("http://x", 5, "инстр", "текст",
                         {"a": "", "none": ""}, limit=0.5) is None

    def test_network_error_propagates(self, mocker):
        """Сетевую ошибку run_query не глотает — пишет вызывающий."""
        mocker.patch("lib.core.laya_batch.urllib.request.urlopen",
                     side_effect=OSError("refused"))
        try:
            run_query("http://x", 5, "инстр", "текст", {"a": "", "none": ""})
            assert False, "ожидался OSError"
        except OSError:
            pass


class TestDetectBatching:
    """Сквозной регресс на 422: большой набор критериев режется на батчи."""

    def test_large_criteria_batches_instead_of_422(self, mocker):
        """>max_opts критериев в detect — несколько запросов ≤ лимита, команда найдена."""
        sizes = []

        def fake_urlopen(url_or_req, timeout=None):
            if isinstance(url_or_req, str):
                return FakeResponse()
            crit = json.loads(url_or_req.data.decode("utf-8"))
            crit = crit["questions"]["command"]["criteria"]
            sizes.append(len(crit))
            return FakeResponse({"answers": {"command": {
                "type": "choice", "choice": "cmd16", "confidence": 0.9}}})

        for mod in ("lib.core.laya_decision", "lib.core.laya_batch"):
            mocker.patch(mod + ".urllib.request.urlopen",
                         side_effect=fake_urlopen)
        client = LayaDecision({"url": "http://x", "threshold": 0.5})
        crit = {f"cmd{i}": f"команда {i}" for i in range(17)}
        res = client.detect("алиса cmd16", criteria=crit)
        assert res is not None and res[0] == "cmd16"
        assert len(sizes) >= 2 and all(n <= MAX_OPTS for n in sizes)
