"""Пуш TTS о начале/конце воспроизведения: шлюз микрофона не должен слушать себя.

Отдельно от test_tts_playback.py (лимит длины файлов): там плееры и файлы,
здесь — уведомление `set_voice_listener`, на которое подписан RecordGate.
"""

from unittest.mock import MagicMock

import pytest

from lib.tts import TextToSpeech


class TestVoiceNotifier:
    """Кто и когда получает переключение «играем / не играем»."""

    def test_play_file_reports_begin_and_end(self):
        """Вокруг `_play_file` слушатель получает True и False."""
        tts = TextToSpeech()
        events = []
        tts.set_voice_listener(events.append)
        tts._play_mp3 = MagicMock(side_effect=lambda *a: events.append("play"))
        tts._play_file(r"C:\tmp\a.mp3")
        assert events == [True, "play", False]

    def test_nested_play_reports_once(self):
        """Вложенные воспроизведения дают один переход 0↔1, а не на каждый блок."""
        tts = TextToSpeech()
        events = []
        tts.set_voice_listener(events.append)
        tts._voice_event(True)
        tts._voice_event(True)
        tts._voice_event(False)
        assert events == [True]
        tts._voice_event(False)
        assert events == [True, False]

    def test_play_failure_still_reports_end(self):
        """Ошибка плеера не оставляет шлюз закрытым навсегда."""
        tts = TextToSpeech()
        events = []
        tts.set_voice_listener(events.append)
        tts._play_mp3 = MagicMock(side_effect=RuntimeError("плеер умер"))
        with pytest.raises(RuntimeError):
            tts._play_file(r"C:\tmp\a.mp3")
        assert events == [True, False]

    def test_broken_listener_does_not_break_playback(self, capsys):
        """Сбой слушателя — только сообщение, озвучка идёт дальше."""
        tts = TextToSpeech()

        def boom(active):
            raise OSError("шлюз сломался")

        tts.set_voice_listener(boom)
        tts._play_wav = MagicMock()
        tts._play_file(r"C:\tmp\a.wav")
        tts._play_wav.assert_called_once()
        assert "Слушатель озвучки" in capsys.readouterr().out

    def test_without_listener_playback_works(self):
        """Без подписчика (шлюз выключен) воспроизведение идёт как обычно."""
        tts = TextToSpeech()
        tts._play_wav = MagicMock()
        tts._play_file(r"C:\tmp\a.wav")
        tts._play_wav.assert_called_once()

    def test_unwound_depth_never_goes_negative(self):
        """Лишний «конец» без начала не ломает счётчик (иначе глохнем навсегда)."""
        tts = TextToSpeech()
        events = []
        tts.set_voice_listener(events.append)
        tts._voice_event(False)
        assert tts._play_depth == 0
        tts._voice_event(True)
        assert tts._play_depth == 1
        assert events == [False, True]
