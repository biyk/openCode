"""Скорость decision-слоя: сколько стоит предварительный /health.

detect() перед каждым запросом к Laya делает HTTP /health. Меряем
health отдельно, полный detect и долю health в detect — это верхняя
граница выигрыша от кэширования проверки доступности сервера.
"""

import platform

import pytest

from lib.core.laya_decision import LayaDecision
from lib.voice_cmd.commands import CommandMatcher
from lib.voice_cmd.config_loader import get_device_commands_path

DETECT_PHRASE = "алиса открой я туб"


@pytest.fixture(scope="module")
def laya():
    """Реальный LayaDecision из конфига устройства (или skip)."""
    matcher = CommandMatcher(get_device_commands_path(platform.node()))
    config = matcher.get_decision_config()
    if not config.get("enabled") or not config.get("url"):
        pytest.skip("decision-слой выключен или без url")
    decision = LayaDecision(config)
    if not decision.available:
        pytest.skip(f"Laya недоступна: {decision.url}")
    return decision


class TestLayaSpeed:
    """Health-check и полный детект."""

    def test_health(self, bench, laya):
        bench.record("laya.health", laya._health, runs=10)

    def test_detect(self, bench, laya):
        bench.record("laya.detect",
                     lambda: laya.detect(DETECT_PHRASE), runs=3)

    def test_health_share(self, bench, laya):
        """Доля /health в времени detect (ради неё кэшируют health)."""
        health = bench.record("laya.health", laya._health, runs=5)
        detect = bench.record("laya.detect",
                              lambda: laya.detect(DETECT_PHRASE), runs=2)
        if detect > 0:
            print(f"[bench] laya.health share of detect: "
                  f"{100 * health / detect:.1f}%")
