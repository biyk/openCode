"""Тесты TextToSpeech: движок Piper и кэш голосов."""


import os
import time
from unittest.mock import patch, MagicMock
from lib.tts import TextToSpeech


class TestTtsPiper:
    """Синтез Piper, загрузка и ошибки моделей."""

    def test_speak_piper_success(self):
        """Успешный синтез через Piper возвращает путь к WAV."""
        tts = TextToSpeech()
        voice = MagicMock()

        def fake_synth(text, out):
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(22050)

        voice.synthesize_wav.side_effect = fake_synth
        with patch.object(tts, "_get_piper_voice", return_value=voice):
            result = tts._speak_piper("Привет")
        assert result is not None
        voice.synthesize_wav.assert_called_once()
        os.unlink(result)

    def test_speak_piper_no_voice(self):
        """Если голос Piper недоступен — возвращается None."""
        tts = TextToSpeech()
        with patch.object(tts, "_get_piper_voice", return_value=None):
            assert tts._speak_piper("Привет") is None

    def test_speak_piper_synthesis_error(self):
        """Ошибка синтеза Piper — None, временный файл удаляется."""
        tts = TextToSpeech()
        voice = MagicMock()
        voice.synthesize_wav.side_effect = Exception("boom")
        with patch.object(tts, "_get_piper_voice", return_value=voice):
            assert tts._speak_piper("Привет") is None

    def test_get_piper_voice_error_flag(self):
        """При установленном флаге ошибки Piper не загружается."""
        tts = TextToSpeech()
        tts._piper_error = True
        assert tts._get_piper_voice() is None

    def test_get_piper_voice_cached(self):
        """Повторный вызов возвращает закешированный голос."""
        tts = TextToSpeech()
        voice = MagicMock()
        tts._piper_voice = voice
        assert tts._get_piper_voice() is voice

    def test_get_piper_voice_model_not_found(self):
        """Если модели нет на диске — флаг ошибки и None."""
        tts = TextToSpeech()
        model = MagicMock()
        model.exists.return_value = False
        with patch("lib.tts_engines._PIPER_MODEL", model):
            assert tts._get_piper_voice() is None
        assert tts._piper_error is True

    def test_get_piper_voice_success(self):
        """Успешная ленивая загрузка модели Piper."""
        tts = TextToSpeech()
        model = MagicMock()
        model.exists.return_value = True
        voice = MagicMock()
        with patch("lib.tts_engines._PIPER_MODEL", model):
            with patch("piper.voice.PiperVoice.load", return_value=voice):
                result = tts._get_piper_voice()
        assert result is voice
        assert tts._piper_voice is voice
        assert tts._piper_error is False

    def test_get_piper_voice_load_error(self):
        """Ошибка загрузки модели Piper — флаг ошибки и None."""
        tts = TextToSpeech()
        model = MagicMock()
        model.exists.return_value = True
        with patch("lib.tts_engines._PIPER_MODEL", model):
            with patch("piper.voice.PiperVoice.load",
                       side_effect=Exception("boom")):
                assert tts._get_piper_voice() is None
        assert tts._piper_error is True

    def test_get_piper_voice_inner_error_flag(self):
        """Флаг ошибки, выставленный внутри локи, возвращает None."""
        import threading
        tts = TextToSpeech()
        holder = {}

        def call():
            holder["result"] = tts._get_piper_voice()

        thread = threading.Thread(target=call)
        tts._piper_lock.acquire()
        thread.start()
        time.sleep(0.1)
        tts._piper_error = True
        tts._piper_lock.release()
        thread.join(timeout=5)
        assert holder["result"] is None
