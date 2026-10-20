# TOOLTIP: Тесты шлюза озвучки: вслух только в наушниках, fail-open, кэш вердикта, фабрика
"""Шлюз озвучки: вслух говорим только когда вывод идёт в наушники (§4.14)."""
from lib.core.tuning import RECORD_GATE_ALLOWED_DEVICE
from lib.runtime.speak_gate import (SPEAK_GATE_TTL_S, SpeakGate,
                                    build_speak_gate)


class FakeOutput:
    """Собирает строки шлюза: переход в молчаливый режим виден в консоли."""

    def __init__(self):
        self.messages = []

    def print_info(self, message):
        self.messages.append(message)


def make_gate(heard, allowed="soundcore H30i", output=None, calls=None,
              ttl_s=SPEAK_GATE_TTL_S):
    """Шлюз на подставной проверке: без COM и без реальных устройств."""
    def probe(token):
        if calls is not None:
            calls.append(token)
        return heard

    return SpeakGate(allowed, output=output, ttl_s=ttl_s, active=probe)


class TestSpeakGateRule:
    """Что считается «наушники подключены»."""

    def test_headphones_allow_voice(self):
        assert make_gate(True).allowed() is True

    def test_speakers_are_silent(self):
        assert make_gate(False).allowed() is False

    def test_unknown_device_fails_open(self):
        """COM не ответил — говорим как раньше, а не замолкаем навсегда."""
        assert make_gate(None).allowed() is True

    def test_probe_error_fails_open(self):
        """Сбой проверки дороже молчания: шлюз открыт."""
        def boom(token):
            raise OSError("hr=0x80004005")

        gate = SpeakGate("soundcore H30i", active=boom)
        assert gate.allowed() is True

    def test_empty_token_does_not_limit(self):
        """Без токена ограничивать не на что: и не дёргаем систему."""
        calls = []
        gate = make_gate(False, allowed="", calls=calls)
        assert gate.allowed() is True
        assert calls == []

    def test_token_is_handed_to_the_probe(self):
        calls = []
        make_gate(True, allowed="haier tv", calls=calls).allowed()
        assert calls == ["haier tv"]


class TestSpeakGateCache:
    """Вердикт держится ttl_s: фраза не меняет решение на середине."""

    def test_second_call_uses_cache(self):
        calls = []
        gate = make_gate(False, calls=calls, ttl_s=60.0)
        assert gate.allowed() is False
        assert gate.allowed() is False
        assert calls == ["soundcore H30i"]

    def test_expired_ttl_probes_again(self):
        calls = []
        gate = make_gate(False, calls=calls, ttl_s=0.0)
        gate.allowed()
        gate.allowed()
        assert len(calls) == 2


class TestSpeakGateTransitions:
    """Переключения: сообщение и запись в реестр — по одному на переход."""

    def test_no_message_while_state_same(self):
        output = FakeOutput()
        gate = make_gate(False, output=output, ttl_s=0.0)
        gate.allowed()
        gate.allowed()
        assert len(output.messages) == 1

    def test_both_transitions_are_reported(self):
        output = FakeOutput()
        heard = [False, True]
        gate = SpeakGate("soundcore H30i", output=output, ttl_s=0.0,
                         active=lambda token: heard.pop(0))
        assert gate.allowed() is False
        assert gate.allowed() is True
        assert len(output.messages) == 2
        assert "SpeakGate" in output.messages[0]
        assert "Молчаливый режим" in output.messages[0]
        assert "Озвучка включена" in output.messages[1]

    def test_without_output_message_goes_to_console(self, capsys):
        make_gate(False).allowed()
        assert "Молчаливый режим" in capsys.readouterr().out


class FakeMatcher:
    """Матчер с тремя секциями, из которых шлюз собирает токен наушников."""

    def __init__(self, speak_gate=None, record_gate=None, mic=None):
        self._speak_gate = speak_gate or {}
        self._record_gate = record_gate or {}
        self._mic = mic or {}

    def get_speak_gate_config(self):
        return self._speak_gate

    def get_record_gate_config(self):
        return self._record_gate

    def get_mic_config(self):
        return self._mic


class TestBuildSpeakGate:
    """Фабрика: секция `speak_gate` commands.json → собранный шлюз."""

    def test_missing_or_disabled_section_returns_none(self):
        """Нет секции (или выключена) — озвучка работает как прежде."""
        assert build_speak_gate(FakeMatcher()) is None
        assert build_speak_gate(FakeMatcher({"enabled": False})) is None

    def test_enabled_takes_token_and_ttl(self):
        gate = build_speak_gate(
            FakeMatcher({"enabled": True, "headphone_device": "haier tv",
                         "ttl_s": 5.0}), FakeOutput())
        assert gate is not None
        assert gate.headphone == "haier tv"
        assert gate._ttl_s == 5.0

    def test_token_falls_back_to_record_gate(self):
        """Своего токена нет — берём разрешённое устройство шлюза захвата."""
        gate = build_speak_gate(
            FakeMatcher({"enabled": True}, {"allowed_device": "BH-07"}))
        assert gate.headphone == "BH-07"

    def test_token_falls_back_to_mic(self):
        gate = build_speak_gate(
            FakeMatcher({"enabled": True}, {}, {"headphone_device": "XB-50"}))
        assert gate.headphone == "XB-50"

    def test_default_token_from_tuning(self):
        gate = build_speak_gate(FakeMatcher({"enabled": True}), FakeOutput())
        assert gate.headphone == RECORD_GATE_ALLOWED_DEVICE
        assert gate._ttl_s == SPEAK_GATE_TTL_S

    def test_build_message_names_the_device(self):
        output = FakeOutput()
        build_speak_gate(FakeMatcher({"enabled": True}), output)
        assert output.messages == [
            "[SpeakGate] Озвучка только в наушниках "
            f"«{RECORD_GATE_ALLOWED_DEVICE}»"]


class TestBuildSpeakGateWithoutMatcher:
    """CLI-озвучка (`python -m lib.tts`) читает конфиг устройства сама."""

    def test_sections_from_file(self, monkeypatch, tmp_path):
        import json
        path = tmp_path / "commands.json"
        path.write_text(json.dumps({"speak_gate": {"enabled": True,
                                                   "headphone_device": "XB"}}),
                        encoding="utf-8")
        monkeypatch.setattr("lib.runtime.speak_gate.get_device_commands_path",
                            lambda name: str(path))
        gate = build_speak_gate()
        assert gate is not None and gate.headphone == "XB"

    def test_no_config_file_fails_open(self, monkeypatch):
        """Нет файла — нет и ограничения: озвучка не должна пропасть."""
        monkeypatch.setattr("lib.runtime.speak_gate.get_device_commands_path",
                            lambda name: "/nope/commands.json")
        assert build_speak_gate() is None
