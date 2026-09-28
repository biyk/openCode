"""Аудиосессии Core Audio: что считать «звучит прямо сейчас»."""
from lib.runtime.audio_devices import is_audible


class TestSessionAudibility:
    """Регресс: играет или нет решает пик-метр, а не AudioState.

    Именно на этом шлюз и глушил микрофон без музыки: свёрнутый плеер висит
    состоянием Active в полной тишине.
    """

    def test_active_but_silent_is_not_sound(self):
        """Active + пик 0.0 — тишина, писать можно."""
        assert is_audible(0, False, 0.0) is False

    def test_state_control_with_peak_is_sound(self):
        """SoundPlayer играет при state=1: состояние не признак воспроизведения."""
        assert is_audible(1, False, 0.6) is True

    def test_muted_stream_is_not_sound(self):
        """Заглушённый поток в микрофон не утекает, даже с пикой."""
        assert is_audible(3, False, 0.6) is False

    def test_system_sounds_are_not_media(self):
        """Сигнаты Windows — не медиа."""
        assert is_audible(0, True, 0.6) is False

    def test_dead_meter_fails_open(self):
        """Метр не ответил — не считаем это воспроизведением."""
        assert is_audible(0, False, None) is False

    def test_min_peak_rejects_dust(self):
        """Порог отсекает шум измерителя ниже уровня слышимости."""
        assert is_audible(0, False, 0.004, 0.01) is False
        assert is_audible(0, False, 0.02, 0.01) is True
