"""Шлюз захвата микрофона: правило «не наушники + играет медиа → не пишем»."""
from lib.core.tuning import RECORD_GATE_ALLOWED_DEVICE, RECORD_GATE_POLL_S
from lib.runtime.record_gate import (RecordGate, build_record_gate,
                                     media_is_playing)

HEADPHONES = "Наушники (soundcore H30i)"
SPEAKERS = "Динамики (Realtek(R) Audio)"


class FakeOutput:
    """Копирует сообщения шлюза (проверяем, что переключение видно в консоли)."""

    def __init__(self):
        self.messages = []

    def print_info(self, message):
        self.messages.append(message)


def make_gate(device, playing, allowed="soundcore H30i", output=None):
    """Шлюз на подставных проверках: без COM и без потока опроса."""
    return RecordGate(allowed_device=allowed, output=output,
                      device_name=lambda: device,
                      media_playing=lambda: playing)


class TestRecordGateRule:
    """Самая таблица случаев правила."""

    def test_headphones_with_media_still_records(self):
        """В наушниках медиа в микрофон не течёт — запись открыта."""
        gate = make_gate(HEADPHONES, True)
        assert gate.tick() is False

    def test_speakers_with_media_blocks(self):
        """С колонок играет — микрофон глушим."""
        gate = make_gate(SPEAKERS, True)
        assert gate.tick() is True

    def test_speakers_silent_records(self):
        """Колонки, но тишина — писать можно."""
        gate = make_gate(SPEAKERS, False)
        assert gate.tick() is False

    def test_unknown_device_fails_open(self):
        """Устройство не опознано — не глушим (сломанная проверка дороже)."""
        gate = make_gate(None, True)
        assert gate.tick() is False

    def test_probe_error_fails_open(self):
        """COM-сбой тоже разворачивает шлюз, а не закрывает его."""
        def boom():
            raise OSError("hr=0x80004005")

        gate = RecordGate(allowed_device="soundcore H30i", device_name=boom,
                          media_playing=lambda: True)
        assert gate.tick() is False

    def test_marker_match_is_case_insensitive(self):
        """Подстрока имени регистр не важна (STT/имена устройств разные)."""
        gate = make_gate("НАУШНИКИ (SoundCore h30i)", True)
        assert gate.tick() is False

    def test_empty_marker_disables_rule(self):
        """Без разрешённого устройства правило молчит — иначе глохли бы всегда."""
        gate = make_gate(SPEAKERS, True, allowed="")
        assert gate.tick() is False


class TestRecordGateTransitions:
    """Переключения: сообщение и флаг для сброса распознавателя."""

    def test_change_flag_reported_once(self):
        """take_change() отдаёт факт переключения ровно один раз."""
        gate = make_gate(SPEAKERS, True, output=FakeOutput())
        gate.tick()
        assert gate.take_change() is True
        assert gate.take_change() is False

    def test_no_change_no_message(self):
        """Повторный опрос без смены состояния ничего не печатает."""
        output = FakeOutput()
        gate = make_gate(SPEAKERS, False, output=output)
        gate.tick()
        gate.tick()
        assert output.messages == []

    def test_blocked_then_open_logs_both(self):
        """Заглушение и возврат — по одному сообщению на переход."""
        output = FakeOutput()
        gate = make_gate(SPEAKERS, True, output=output)
        gate.tick()
        gate._media_playing = lambda: False
        gate.tick()
        assert gate.blocked is False
        assert len(output.messages) == 2
        assert "RecordGate" in output.messages[0]


class TestMediaProbe:
    """Кто считается медиа, а кто — собственным звуком ассистента."""

    def test_own_tts_player_is_not_media(self, mocker):
        """powershell (озвучка TTS) не должен глушить микрофон."""
        mocker.patch("lib.runtime.record_gate.active_session_processes",
                     return_value=["powershell.exe"])
        assert media_is_playing(("powershell.exe", "python.exe")) is False

    def test_foreign_player_is_media(self, mocker):
        """Браузер с роликом — это медиа, шлюз закрывается."""
        mocker.patch("lib.runtime.record_gate.active_session_processes",
                     return_value=["brave.exe"])
        assert media_is_playing(("powershell.exe",)) is True

    def test_silence_is_not_media(self, mocker):
        """Пустой список сессий — тишина."""
        mocker.patch("lib.runtime.record_gate.active_session_processes",
                     return_value=[])
        assert media_is_playing(()) is False

    def test_threshold_reaches_session_probe(self, mocker):
        """Порог пик-метра проходит в перечисление сессий (иначе тишина вернётся)."""
        probe = mocker.patch("lib.runtime.record_gate.active_session_processes",
                             return_value=[])
        media_is_playing((), 0.05)
        probe.assert_called_once_with(0.05)


class FakeMatcher:
    """Матчер с одной секцией конфига."""

    def __init__(self, config):
        self._config = config

    def get_record_gate_config(self):
        return self._config


class TestBuildRecordGate:
    """Фабрика: секция `record_gate` commands.json → собранный шлюз."""

    def test_disabled_section_returns_none(self):
        """Нет секции (или выключена) — никакого шлюза и потока."""
        output = FakeOutput()
        assert build_record_gate(FakeMatcher({}), output) is None
        assert build_record_gate(FakeMatcher({"enabled": False}), output) is None
        assert output.messages == []

    def test_enabled_builds_gate_from_config_without_start(self, mocker):
        """enabled берёт allowed_device/poll_s из конфига; поток — за run()."""
        start = mocker.patch.object(RecordGate, "start")
        gate = build_record_gate(
            FakeMatcher({"enabled": True, "allowed_device": "haier tv",
                         "poll_s": 2.5,
                         "ignored_processes": ["PowerShell.EXE"]}),
            FakeOutput())
        assert gate is not None
        assert gate.allowed == "haier tv"
        assert gate._poll_s == 2.5
        start.assert_not_called()

    def test_min_peak_from_config_reaches_probe(self, mocker):
        """min_peak секции уходит в проверку сессий вместе со списком скидок."""
        playing = mocker.patch("lib.runtime.record_gate.media_is_playing",
                               return_value=False)
        gate = build_record_gate(
            FakeMatcher({"enabled": True, "min_peak": 0.2}), FakeOutput())
        gate._media_playing()
        playing.assert_called_once_with(
            ("powershell.exe", "python.exe", "pythonw.exe", "mpg123.exe",
             "ffplay.exe"), 0.2)

    def test_defaults_from_tuning_when_keys_absent(self):
        """Без ключов секции — дефолты из lib.core.tuning."""
        gate = build_record_gate(FakeMatcher({"enabled": True}), FakeOutput())
        assert gate.allowed == RECORD_GATE_ALLOWED_DEVICE.casefold()
        assert gate._poll_s == RECORD_GATE_POLL_S
