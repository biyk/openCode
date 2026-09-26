"""Общие фикстуры тестов.

Живые (live) тесты, которые реально дёргают систему (громкость,
браузер), используют фикстуру live_announce — она один раз за сессию
озвучивает предупреждение, чтобы тестирование не пугало, а в конце
сессии озвучивает «Тестирование завершено».
"""

import pytest

_live_announced = False


def _speak(text: str) -> None:
    """Озвучивает текст через TTS, не роняя тестовую сессию при ошибке."""
    try:
        from lib.tts import TextToSpeech
        TextToSpeech().speak_and_play(text)
    except Exception as e:
        print(f"[live_announce] Озвучка не удалась: {e}")


@pytest.fixture(scope="session")
def live_announce():
    """Один раз озвучивает «Внимание, идёт тестирование»."""
    global _live_announced
    _speak("Внимание, идёт тестирование")
    _live_announced = True
    yield


def pytest_sessionfinish(session, exitstatus):
    """После live-прогона озвучивает «Тестирование завершено»."""
    if _live_announced:
        _speak("Тестирование завершено")
