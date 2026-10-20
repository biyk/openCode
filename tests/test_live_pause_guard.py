# TOOLTIP: Тесты paused_app: ассистент обязан вернуться живым при любом исходе
"""Контракт глушения приложения на время live-тестов.

Живые тесты (громкость, браузер, календарь) не работают поверх крутящегося
ассистента, поэтому сессия выключает его через resurrector (`enabled = false`)
и обязана включить обратно. Раньше `set_enabled(False)` стоял ДО try/finally:
исключение в проверке процессов оставляло ассистента выключенным, а
следующий прогон считал «исходным» уже выключенное состояние и честно
восстанавливал его — то есть молча оставлял пользователя без ассистента.
"""

import pytest

from tests import resurrector_control as rc


class FakeConfig:
    """Замена чтения/записи resurrector: журнал вызовов вместо живого файла."""

    def __init__(self, enabled):
        self.enabled = enabled
        self.writes = []

    def get_enabled(self):
        return self.enabled

    def set_enabled(self, value):
        self.writes.append(value)
        self.enabled = value
        return True


@pytest.fixture
def patch_config(monkeypatch):
    def _patch(enabled, wait=None):
        fake = FakeConfig(enabled)
        monkeypatch.setattr(rc, "get_enabled", fake.get_enabled)
        monkeypatch.setattr(rc, "set_enabled", fake.set_enabled)
        monkeypatch.setattr(rc, "wait_app_stopped",
                            wait or (lambda *a, **kw: True))
        return fake
    return _patch


class TestRestoreHappensAnyway:
    """Включение обратно — не привилегия удачного прогона."""

    def test_pause_crash_still_enables_app(self, patch_config):
        """Сбой ожидания остановки НЕ должен оставлять enabled=false."""
        def boom(timeout=15.0):
            raise RuntimeError("процессы не опросились")

        fake = patch_config(True, wait=boom)
        with pytest.raises(RuntimeError):
            with rc.paused_app():
                pass
        assert fake.writes == [False, True], (
            f"after crash config is {fake.enabled}, writes {fake.writes}")
        assert fake.enabled is True

    def test_test_failure_still_enables_app(self, patch_config):
        """Исключение внутри самих тестов — состояние тоже возвращается."""
        fake = patch_config(True)
        with pytest.raises(ValueError):
            with rc.paused_app():
                raise ValueError("live-тест упал")
        assert fake.writes == [False, True]

    def test_happy_path_pauses_and_restores(self, patch_config):
        fake = patch_config(True)
        with rc.paused_app() as paused:
            assert paused is True
            assert fake.enabled is False
        assert paused is True
        assert fake.writes == [False, True]


class TestAlreadyOffIsNotTouched:
    """Выключенное ДО нас состояние — не «исходное», его не восстанавливают."""

    def test_disabled_before_session_is_left_alone(self, patch_config):
        fake = patch_config(False)
        with rc.paused_app() as paused:
            assert paused is False
        assert fake.writes == [], (
            "приложение было выключено пользователем — тесты не должны "
            "ни гасить его повторно, ни «восстанавливать» выключенным")

    def test_no_section_is_left_alone(self, patch_config):
        fake = patch_config(None)
        with rc.paused_app() as paused:
            assert paused is False
        assert fake.writes == []
