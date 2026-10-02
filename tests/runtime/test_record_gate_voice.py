"""Тесты шлюза записи против собственной озвучки: пуш TTS, хвост, подписка.

Отдельно от test_record_gate.py (лимит длины файлов): там правило «наушники/
колонки + медиа», здесь — что голос ассистента считается таким же медиа.
"""
from lib.core.tuning import RECORD_GATE_VOICE_TAIL_S
from lib.runtime.record_gate import RecordGate, build_record_gate

HEADPHONES = "Наушники (soundcore H30i)"
SPEAKERS = "Динамики (Realtek(R) Audio)"


class FakeOutput:
    """Копирует сообщения шлюза (видно, чем именно он заглушён)."""

    def __init__(self):
        self.messages = []

    def print_info(self, message):
        self.messages.append(message)


class FakeMatcher:
    """Матчер с одной секцией конфига."""

    def __init__(self, config):
        self._config = config

    def get_record_gate_config(self):
        return self._config


class FakeTts:
    """TTS, записывающий подписку шлюза (дальше слушатель зовётся вручную)."""

    def __init__(self):
        self.listener = None

    def set_voice_listener(self, listener):
        self.listener = listener


def make_gate(device, playing=False, output=None, tail_s=0.5):
    """Шлюз на подставных проверках: без COM и без потока опроса."""
    return RecordGate(allowed_device="soundcore H30i", output=output,
                      device_name=lambda: device,
                      media_playing=lambda: playing, voice_tail_s=tail_s)


class TestRecordGateOwnVoice:
    """Своя озвучка — тоже медиа: шлюз закрывается без лага опроса."""

    def test_voice_blocks_without_waiting_for_tick(self):
        """Пуш озвучки закрывает шлюз сразу, а не на следующем tick()."""
        output = FakeOutput()
        gate = make_gate(SPEAKERS, output=output)
        gate.tick()
        gate.voice(True)
        assert gate.blocked is True
        assert "говорю сам" in output.messages[-1]

    def test_voice_in_headphones_never_blocks(self):
        """В наушниках своя озвучка в микрофон не течёт — пишем."""
        gate = make_gate(HEADPHONES)
        gate.tick()
        gate.voice(True)
        assert gate.blocked is False

    def test_voice_before_first_tick_fails_open(self):
        """Пока устройство не опознано — не глушим, но первый опрос догоняет."""
        gate = make_gate(SPEAKERS)
        gate.voice(True)
        assert gate.blocked is False
        assert gate.tick() is True

    def test_tail_holds_gate_then_releases(self, mocker):
        """Хвост держит шлюз закрытым, по его истечении он открывается."""
        now = [100.0]
        mocker.patch("lib.runtime.record_gate.time.monotonic",
                     side_effect=lambda: now[0])
        gate = make_gate(SPEAKERS)
        gate.tick()
        gate.voice(True)
        gate.voice(False)
        assert gate.blocked is True
        now[0] += 1.0
        assert gate.tick() is False

    def test_blocks_of_one_phrase_do_not_flicker(self):
        """Конец блока и старт следующего (в пределах хвоста) — без переключений."""
        output = FakeOutput()
        gate = make_gate(SPEAKERS, output=output)
        gate.tick()
        gate.voice(True)
        gate.voice(False)
        gate.voice(True)
        assert gate.blocked is True
        assert [m for m in output.messages if "открыта" in m] == []

    def test_media_keeps_gate_closed_after_voice_ends(self, mocker):
        """Чужое медиа, пойманный опросом, не отпускает шлюз вслед за озвучкой."""
        now = [100.0]
        mocker.patch("lib.runtime.record_gate.time.monotonic",
                     side_effect=lambda: now[0])
        gate = make_gate(SPEAKERS, playing=True)
        gate.tick()
        gate.voice(True)
        gate.voice(False)
        now[0] += 1.0
        assert gate.tick() is True


class TestVoiceSubscription:
    """Фабрика подписывает TTS на шлюз (и не подписывает, когда шлюза нет)."""

    def test_voice_object_subscribed_to_gate(self):
        """TTS получает слушателя переключений: озвучка глохнет без лага опроса."""
        tts = FakeTts()
        gate = build_record_gate(FakeMatcher({"enabled": True}), FakeOutput(),
                                 voice=tts)
        assert tts.listener == gate.voice

    def test_disabled_section_does_not_subscribe(self):
        """Выключенный шлюз никого не подписывает (иначе TTS кричит в пустоту)."""
        tts = FakeTts()
        assert build_record_gate(FakeMatcher({}), FakeOutput(),
                                 voice=tts) is None
        assert tts.listener is None

    def test_tail_from_config_reaches_gate(self):
        """voice_tail_s секции — порог хвоста шлюза; без него — дефолт tuning."""
        gate = build_record_gate(
            FakeMatcher({"enabled": True, "voice_tail_s": 1.5}), FakeOutput())
        assert gate._tail_s == 1.5
        default = build_record_gate(FakeMatcher({"enabled": True}),
                                    FakeOutput())
        assert default._tail_s == RECORD_GATE_VOICE_TAIL_S
