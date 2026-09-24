"""Общие фикстуры тестов.

Живые (live) тесты, которые реально дёргают систему (громкость,
браузер), используют фикстуру live_announce — она один раз за сессию
озвучивает предупреждение, чтобы тестирование не пугало.
"""

import pytest


@pytest.fixture(scope="session")
def live_announce():
    """Один раз озвучивает «Внимание, идёт тестирование»."""
    try:
        from lib.tts import TextToSpeech
        TextToSpeech().speak_and_play("Внимание, идёт тестирование")
    except Exception as e:
        print(f"[live_announce] Озвучка не удалась: {e}")
    yield
