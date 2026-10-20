# TOOLTIP: Тесты молчаливого режима TTS: шлюз режет и синтез, и плеер, и не молчит при сбое
"""Молчаливый режим озвучки: шлюз (§4.14) режет и синтез, и плеер."""
from lib.tts import TextToSpeech


class DenyGate:
    """Шлюз, который всегда молчит (наушников на выводе нет)."""

    headphone = "soundcore H30i"

    def __init__(self):
        self.calls = 0

    def allowed(self):
        self.calls += 1
        return False


class AllowGate(DenyGate):
    """Шлюз «звук в наушниках»: озвучка работает как прежде."""

    def allowed(self):
        self.calls += 1
        return True


class TestTtsSilentMode:
    """Что происходит с фразой, когда говорить вслух нельзя."""

    def test_denied_phrase_is_not_synthesized(self, mocker, capsys):
        """Ни сети на синтез, ни плеера — молчание только про звук."""
        speak = mocker.patch.object(TextToSpeech, "speak")
        play = mocker.patch.object(TextToSpeech, "_play_file")
        tts = TextToSpeech()
        tts.set_speak_gate(DenyGate())
        tts.speak_and_play("Открой браузер.")
        speak.assert_not_called()
        play.assert_not_called()
        assert tts.audible is False
        assert "Молчу" in capsys.readouterr().out

    def test_denied_phrase_still_calls_on_finished(self, mocker):
        """Оркестратор снимает флаг озвучки по on_finished — он обязателен."""
        mocker.patch.object(TextToSpeech, "speak")
        done = []
        tts = TextToSpeech()
        tts.set_speak_gate(DenyGate())
        tts.speak_blocks(["Первое.", "Второе."], on_finished=lambda: done.append(1))
        assert done == [1]

    def test_allowed_phrase_plays(self, mocker):
        """В наушниках — обычный путь: синтез и проигрывание блоков."""
        mocker.patch.object(TextToSpeech, "speak",
                            side_effect=lambda t, abort_event=None: "/tmp/x.mp3")
        play = mocker.patch.object(TextToSpeech, "_play_file")
        tts = TextToSpeech(max_workers=2)
        tts.set_speak_gate(AllowGate())
        tts.speak_and_play("Первое. Второе.")
        assert play.call_count == 2
        assert tts.audible is True

    def test_gate_is_consulted_once_per_phrase(self, mocker):
        """Вердикт берут до нарезки на блоки: multiple блоки — один опрос."""
        mocker.patch.object(TextToSpeech, "speak",
                            side_effect=lambda t, abort_event=None: "/tmp/x.mp3")
        mocker.patch.object(TextToSpeech, "_play_file")
        gate = AllowGate()
        tts = TextToSpeech(max_workers=2)
        tts.set_speak_gate(gate)
        tts.speak_and_play("Первое. Второе. Третье.")
        assert gate.calls == 1

    def test_empty_text_never_asks_the_gate(self, mocker):
        """Пустая фраза — прежнее «Пустой текст»; шлюз не дёргаем."""
        mocker.patch.object(TextToSpeech, "speak")
        mocker.patch.object(TextToSpeech, "_play_file")
        gate = DenyGate()
        tts = TextToSpeech()
        tts.set_speak_gate(gate)
        done = []
        tts.speak_blocks(["", "  "], on_finished=lambda: done.append(1))
        assert gate.calls == 0
        assert done == [1]

    def test_no_gate_plays_as_before(self, mocker):
        """Секция speak_gate выключена — озвучка не меняется."""
        mocker.patch.object(TextToSpeech, "speak",
                            side_effect=lambda t, abort_event=None: "/tmp/x.mp3")
        play = mocker.patch.object(TextToSpeech, "_play_file")
        tts = TextToSpeech()
        tts.set_speak_gate(None)
        tts.speak_and_play("Готово")
        play.assert_called_once_with("/tmp/x.mp3", None)
        assert tts.audible is True

    def test_gate_failure_does_not_silence_the_phrase(self, mocker, capsys):
        """Сломанный шлюз — говорим как раньше (fail-open), а не молчим.

        Промолчать из-за упавшей проверки хуже, чем сказать вслух: решение
        о молчании должно быть только положительным (§4.14).
        """
        class BrokenGate:
            headphone = "soundcore H30i"

            def allowed(self):
                raise OSError("com")

        mocker.patch.object(TextToSpeech, "speak",
                            side_effect=lambda t, abort_event=None: "/tmp/x.mp3")
        play = mocker.patch.object(TextToSpeech, "_play_file")
        tts = TextToSpeech()
        tts.set_speak_gate(BrokenGate())
        tts.speak_and_play("Шлюз упал")
        play.assert_called_once_with("/tmp/x.mp3", None)
        assert tts.audible is True
        assert "Шлюз озвучки" in capsys.readouterr().out
