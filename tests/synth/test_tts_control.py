"""Тесты TTS: прерывания, колбэки, _decode_arg, CLI."""


import threading
from unittest.mock import patch
from lib.tts import TextToSpeech, _decode_arg, main


class TestTtsControl:
    """Abort до/после speak/play и колбэки аудио."""

    def test_speak_and_play_single_abort_before_speak(self):
        """Прерывание до синтеза пропускает и синтез, и воспроизведение."""
        tts = TextToSpeech()
        abort = threading.Event()
        abort.set()
        called = []
        with patch.object(tts, "speak") as mock_speak:
            with patch.object(tts, "_play_file") as play:
                tts._speak_and_play_single(
                    "x", lambda: called.append(1), abort_event=abort)
        assert called == [1]
        mock_speak.assert_not_called()
        play.assert_not_called()

    def test_speak_and_play_single_abort_before_play(self):
        """Прерывание после синтеза пропускает воспроизведение."""
        tts = TextToSpeech()
        abort = threading.Event()

        def fake_speak(text: str, abort_event=None) -> str:
            abort.set()
            return "/tmp/a.mp3"

        called = []
        with patch.object(tts, "speak", side_effect=fake_speak) as mock_speak:
            with patch.object(tts, "_play_file") as play:
                tts._speak_and_play_single(
                    "x", lambda: called.append(1), abort_event=abort)
        assert called == [1]
        mock_speak.assert_called_once()
        play.assert_not_called()

    def test_speak_and_play_pipeline_abort_stops_playback(self):
        """Прерывание пайплайна останавливает дальнейшее воспроизведение."""
        tts = TextToSpeech(max_workers=4)
        abort = threading.Event()
        played = []

        def fake_play(path, abort_event=None):
            played.append(path)
            abort.set()

        with patch.object(tts, "speak",
                          side_effect=["/tmp/1.mp3", "/tmp/2.mp3"]):
            with patch.object(tts, "_play_file", side_effect=fake_play):
                tts._speak_and_play_pipeline(
                    "Один. Два.", None, abort_event=abort)
        assert played == ["/tmp/1.mp3"]

    def test_speak_and_play_pipeline_abort_before_play(self):
        """Прерывание до первого блока не играет ничего."""
        tts = TextToSpeech(max_workers=4)
        abort = threading.Event()
        abort.set()
        with patch.object(tts, "speak"):
            with patch.object(tts, "_play_file") as play:
                tts._speak_and_play_pipeline(
                    "Один. Два.", None, abort_event=abort)
        play.assert_not_called()

    def test_speak_and_play_single_no_audio_callback(self):
        """on_finished вызывается, даже если аудио не создано."""
        tts = TextToSpeech()
        called = []
        with patch.object(tts, "speak", return_value=None):
            with patch.object(tts, "_play_file") as play:
                tts._speak_and_play_single("x", lambda: called.append(1))
        assert called == [1]
        play.assert_not_called()

    def test_speak_and_play_single_callback_after_play(self):
        """on_finished вызывается после воспроизведения."""
        tts = TextToSpeech()
        called = []
        with patch.object(tts, "speak", return_value="/tmp/a.mp3"):
            with patch.object(tts, "_play_file"):
                tts._speak_and_play_single("x", lambda: called.append(1))
        assert called == [1]

    def test_speak_and_play_pipeline_callback(self):
        """on_finished вызывается для пайплайна."""
        tts = TextToSpeech()
        called = []
        with patch.object(tts, "speak", return_value=None):
            with patch.object(tts, "_play_file"):
                tts._speak_and_play_pipeline(
                    "Один. Два.", lambda: called.append(1))
        assert called == [1]

    def test_speak_and_play_empty_text_callback(self):
        """on_finished вызывается при пустом тексте."""
        tts = TextToSpeech()
        called = []
        tts.speak_and_play("", lambda: called.append(1))
        assert called == [1]


class TestDecodeArg:
    """Расшифровка аргументов командной строки."""

    def test_plain_text_passthrough(self):
        """Обычный текст без префикса возвращается как есть."""
        assert _decode_arg("Задача выполнена") == "Задача выполнена"

    def test_b64_with_quotes_and_cyrillic(self):
        """Base64 сохраняет кавычки и кириллицу (проблема cp1251-консоли)."""
        import base64
        phrase = 'Нет задачи "починить лампочку" в списке'
        arg = "--b64:" + base64.b64encode(phrase.encode("utf-8")).decode("ascii")
        assert _decode_arg(arg) == phrase

    def test_b64_bad_payload_falls_back(self):
        """Некорректный base64 («123» не валиден) возвращает строку как есть."""
        assert _decode_arg("--b64:123") == "--b64:123"


class TestMainCli:
    """CLI-точка входа TTS."""

    def test_no_args_returns_2(self):
        assert main([]) == 2

    @patch("lib.tts.TextToSpeech.speak_and_play")
    def test_plain_arg_spoken(self, mock_speak):
        assert main(["Задача выполнена"]) == 0
        mock_speak.assert_called_once_with("Задача выполнена")

    @patch("lib.tts.TextToSpeech.speak_and_play")
    def test_b64_arg_decoded_and_spoken(self, mock_speak):
        import base64
        phrase = '"починить" лампочку'
        arg = "--b64:" + base64.b64encode(phrase.encode("utf-8")).decode("ascii")
        assert main([arg]) == 0
        mock_speak.assert_called_once_with(phrase)
