"""Скорость LLM-гонки: overhead classify() и цена повтора запроса.

race.classify_repeat_pair — время классифицировать ОДИН ЖЕ текст два
раза подряд (эхо STT, повторные вопросы dedup). Сейчас это 2 полных
гона; метрика падает примерно вдвое, когда кэш результатов появится.
Провайдеры моделируются искусственной задержкой — без живых запросов.
"""

import time

from bench import live_only
from lib.providers.race import RaceClient

REPEAT_TEXT = "определи команду: открыть youtube"


def _race_with(omni_delay: float, lm_delay: float) -> RaceClient:
    """RaceClient с мок-провайдерами, «отвечающими» с задержкой."""

    def _omni(text):
        time.sleep(omni_delay)
        return "openyoutube"

    def _lm(text):
        time.sleep(lm_delay)
        return "NONE"

    client = RaceClient(timeout=5)
    client._omni.ask = _omni
    client._lmstudio.ask = _lm
    return client


class TestRaceSpeed:
    """Механика гонки без сети: потоки, очереди, дубли запросов."""

    def test_classify_overhead(self, bench):
        """Чистый overhead classify() (провайдеры отвечают мгновенно)."""
        client = _race_with(0.0, 0.0)
        bench.record("race.classify_overhead",
                     lambda: client.classify("громче"), runs=30)

    def test_classify_single(self, bench):
        """Одна классификация с задержкой провайдера 0.2 с."""
        client = _race_with(0.2, 0.4)
        bench.record("race.classify_single",
                     lambda: client.classify(REPEAT_TEXT), runs=3)

    def test_classify_repeat_pair(self, bench):
        """Две одинаковые классификации подряд: цена отсутствия кэша."""
        client = _race_with(0.2, 0.4)

        def _pair():
            client.classify(REPEAT_TEXT)
            client.classify(REPEAT_TEXT)

        bench.record("race.classify_repeat_pair", _pair, runs=3)

    @live_only
    def test_classify_live(self, bench):
        """Живые провайдеры (VOICE_SPEED_LIVE=1): реальная latency гонки."""
        client = RaceClient(timeout=30)
        bench.record("race.classify_live",
                     lambda: client.classify(REPEAT_TEXT, timeout=25),
                     runs=2)

    @live_only
    def test_classify_live_repeat_pair(self, bench):
        """Живые провайдеры, один текст дважды (baseline для кэша)."""
        client = RaceClient(timeout=30)

        def _pair():
            client.classify(REPEAT_TEXT, timeout=25)
            client.classify(REPEAT_TEXT, timeout=25)

        bench.record("race.classify_live_repeat_pair", _pair, runs=1)
