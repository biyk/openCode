"""Двухступенчатый выбор Лайи: победитель батча → финал среди победителей.

query_batches из каждого батча берёт победителя, затем финальный вопрос
final(sub_crit) выбирает лучшего среди них (уверенности разных батчей
некалиброваны). Финал решает: none/ниже порога — команды нет. Сквозная
проверка detect: какие критерии и какая инструкция уходят в финал.
"""

import json

from lib.core.laya_batch import query_batches
from lib.core.laya_decision import FINAL_INSTRUCTIONS, LayaDecision


class FakeResponse:
    """Файлоподобный ответ urllib (status=200 — годен и для /health)."""

    def __init__(self, payload=None):
        self._payload = payload
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def _crit(n=16):
    crit = {f"c{i}": f"оп {i}" for i in range(n)}
    crit["none"] = "нд"
    return crit


class TestQueryBatchesFinalStage:
    def test_final_choice_beats_batch_argmax(self):
        """Финал перебивает более уверенный батч: решает финальный вопрос."""
        def single(sub):
            return ("c9", 0.99, 0.1) if "c9" in sub else ("c0", 0.70, 0.1)

        finals = {}

        def final(sub):
            finals.update(sub)
            return ("c0", 0.95, 0.2)  # победил менее уверенный в батче

        res = query_batches(_crit(), single, final=final)
        assert res == ("c0", 0.95, 0.4)  # elapsed = 0.1+0.1+0.2
        assert set(finals) == {"c0", "c9", "none"}

    def test_final_none_vetoes_winners(self):
        """Финал сказал none (run_query → None) — команды нет целиком."""
        def single(sub):
            return ("c9", 0.99, 0.1) if "c9" in sub else ("c0", 0.95, 0.1)

        assert query_batches(_crit(), single, final=lambda s: None) is None

    def test_single_winner_skips_final(self):
        """Победитель один — сравнивать не с чем, финал не задаём."""
        def single(sub):
            return ("c15", 0.95, 0.1) if "c15" in sub else None

        def final(sub):
            raise AssertionError("финал не вызывается при одном победителе")

        assert query_batches(_crit(), single, final=final) == ("c15", 0.95,
                                                               0.1)

    def test_no_final_callable_keeps_argmax(self):
        """final=None (чужие вызовы, напр. моки) — старый аргмакс."""
        def single(sub):
            return ("c9", 0.99, 0.1) if "c9" in sub else ("c0", 0.70, 0.1)

        assert query_batches(_crit(), single)[0] == "c9"


class TestDetectFinalStage:
    """Сквозной detect: финальный вопрос идёт по победителям и своей инстр."""

    def test_detect_asks_final_over_winners(self, mocker):
        requests = []

        def fake_urlopen(url_or_req, timeout=None):
            if isinstance(url_or_req, str):
                return FakeResponse()  # /health
            q = json.loads(url_or_req.data.decode("utf-8"))
            q = q["questions"]["command"]
            crit = q["criteria"]
            keys = sorted(k for k in crit if k != "none")
            requests.append((keys, q["instructions"]))
            return FakeResponse({"answers": {"command": {
                "choice": keys[0], "confidence": 0.95}}})

        for mod in ("lib.core.laya_decision", "lib.core.laya_batch"):
            mocker.patch(mod + ".urllib.request.urlopen",
                         side_effect=fake_urlopen)
        client = LayaDecision({"url": "http://x", "threshold": 0.5})
        res = client.detect("алиса c9", criteria=_crit(16))
        # два батча по 8 → два победителя → третий запрос — финал по ним
        assert len(requests) == 3
        finals, instr = requests[-1]
        # победители — первые (по сортировке) ключи батчей: c0 и c10
        assert finals == ["c0", "c10"]
        assert instr == FINAL_INSTRUCTIONS
        assert res[0] == "c0"
