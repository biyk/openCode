"""Скоростные замеры: обычные прогоны pytest их НЕ запускают.

Запуск только по запросу (env VOICE_SPEED=1):
  $env:VOICE_SPEED="1"; python -m pytest tests/speed -v -s

Результаты с историей — tests/speed/results.json: после очередной
оптимизации сравниваем старые и новые медианы (дельта печатается
в консоль). Живые LLM-запросы меряются только с VOICE_SPEED_LIVE=1.
"""

import os

import pytest

from bench import Recorder

_SPEED_DIR = os.path.dirname(os.path.abspath(__file__))


def pytest_collection_modifyitems(config, items):
    """Без VOICE_SPEED=1 помечаются skip только замеры этой папки.

    Хук глобален и получает ВСЕ собранные тесты, поэтому фильтруем
    по пути — иначе глушили бы весь прогон (регрессия, поймана мерами).
    """
    if os.environ.get("VOICE_SPEED") == "1":
        return
    skip = pytest.mark.skip(reason="скоростные замеры: VOICE_SPEED=1")
    for item in items:
        path = os.path.abspath(str(item.fspath))
        if path.startswith(_SPEED_DIR):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def bench():
    """Один рекордер results.json на сессию."""
    return Recorder()
