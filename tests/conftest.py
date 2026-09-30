"""Общие фикстуры тестов.

Живые (live) тесты, которые реально дёргают систему (громкость,
браузер), используют фикстуру live_announce — она один раз за сессию
озвучивает предупреждение, чтобы тестирование не пугало, а в конце
сессии озвучивает «Тестирование завершено».

Крутящийся рядом экземпляр ассистента мешает живым тестам: медиа-клавиши
громкости не доходят, аудио-сессии конфликтуют. Поэтому на всю сессию с
live-тестами приложение глушится через resurrector (флаг enabled=false —
чтобы вотчдог не пересоздавал процесс), а после прогона включается обратно.
"""

import platform

import pytest

_live_announced = False
_live_selected = False


def pytest_collection_modifyitems(session, config, items):
    """Отмечает, есть ли в прогоне живые тесты (пути *_live.py)."""
    global _live_selected
    _live_selected = any("_live" in str(item.fspath) for item in items)


def _speak(text: str) -> None:
    """Озвучивает текст через TTS, не роняя тестовую сессию при ошибке."""
    try:
        from lib.tts import TextToSpeech
        TextToSpeech().speak_and_play(text)
    except Exception as e:
        print(f"[live_announce] Озвучка не удалась: {e}")


@pytest.fixture(scope="session", autouse=True)
def pause_app_for_live_session():
    """Глушит приложение в начале live-сессии и включает в конце.

    Только для прогонов с живыми тестами и только на Windows; иначе —
    no-op, чтобы юнит-прогоны не гасили рабочее приложение. Состояние
    resurrector возвращается обязательно (даже при падении тестов).
    """
    if not _live_selected or platform.system() != "Windows":
        yield
        return
    from tests.resurrector_control import (
        get_enabled, set_enabled, wait_app_stopped,
    )
    original = get_enabled()
    if original is None:
        yield
        return
    set_enabled(False)
    wait_app_stopped()
    try:
        yield
    finally:
        set_enabled(original)


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
