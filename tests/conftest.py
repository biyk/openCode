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
    no-op, чтобы юнит-прогоны не гасили рабочее приложение. Всю работу делает
    `resurrector_control.paused_app`: состояние возвращается независимо от
    того, упал ли прогон (или сама подготовка к нему).
    """
    if not _live_selected or platform.system() != "Windows":
        yield
        return
    from tests.resurrector_control import paused_app
    with paused_app():
        yield


@pytest.fixture(autouse=True)
def reset_sleep_gate():
    """Обнуляет кэш вердикта «СОН».

    `lib/core/sleep_gate.py` — модульный синглтон: без сброса тест, поймавший
    «спим», оставил бы молчащими все последующие тесты монитора и Telegram.
    """
    from lib.core.sleep_gate import set_sleeping
    set_sleeping(False)
    yield
    set_sleeping(False)


@pytest.fixture(autouse=True)
def headphones_for_tts(monkeypatch):
    """Тесты «в наушниках»: шлюз озвучки (§4.14) не должен глушить моки.

    `TextToSpeech` сам строит SpeakGate по конфигу устройства, и тесты с
    настоящим TTS (`tests/synth/test_tts*.py`, живые озвучки здесь же)
    зависели бы от того, что сейчас подключено к ПК. Шлюз зовёт проверку по
    имени модуля (поздняя привязка в `SpeakGate._active`), поэтому подмена
    работает и для уже собранного шлюза; тесты самого шлюза подменяют её
    заново под свои случаи.
    """
    from lib.runtime import speak_gate
    monkeypatch.setattr(speak_gate, "headset_active", lambda token: True)
    yield


@pytest.fixture(autouse=True)
def isolated_tts_cache(tmp_path, monkeypatch):
    """Тестам недоступен живой кэш mp3 (`temp/mp3`) — там файлы ассистента.

    Без подмены тесты синтеза кладут в общий кэш байты своих моков (фраза
    "Привет" из test.mp3 в корне репо), а следующий `speak("Привет")` находит
    эту запись, пропускает синтез и возвращает кэш вместо мока gTTS — тесты
    движков падают уже на втором прогоне. Тесты, которые сами передвигают
    `CACHE_DIR` (tests/synth/test_tts_cache.py, test_tts_pipeline.py), делают
    это monkeypatch'ом позже — их подмена и остаётся действующей.
    """
    from lib.synth import tts_cache
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path / "mp3")
    yield


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
