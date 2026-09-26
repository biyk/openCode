"""Тесты TextToSpeech: синтез и фолбэки движков."""


import tempfile
import threading
from unittest.mock import patch, MagicMock
from lib.tts import TextToSpeech


class TestTtsSpeak:
    """Инициализация, speak, gTTS/piper/sapi фолбэки."""

    def test_init_default_lang(self):
        tts = TextToSpeech()
        assert tts._lang == "ru"

    def test_init_custom_lang(self):
        tts = TextToSpeech(lang="en")
        assert tts._lang == "en"

    def test_speak_empty_text(self, capsys):
        tts = TextToSpeech()
        result = tts.speak("")
        assert result is None

    def test_speak_none_text(self, capsys):
        tts = TextToSpeech()
        result = tts.speak(None)
        assert result is None

    def test_speak_abort_returns_none(self, capsys):
        """При установленном abort_event синтез пропускается."""
        tts = TextToSpeech()
        abort = threading.Event()
        abort.set()
        with patch.object(tts, "_speak_gtts") as mock_gtts:
            result = tts.speak("Привет", abort_event=abort)
        assert result is None
        mock_gtts.assert_not_called()

    @patch("lib.synth.tts_engines.gTTS")
    def test_speak_success(self, mock_gtts, capsys):
        mock_tts = MagicMock()
        mock_gtts.return_value = mock_tts

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("lib.synth.tts_engines.tempfile.NamedTemporaryFile") as mock_temp:
                mock_file = MagicMock()
                mock_file.name = f"{tmpdir}/test.mp3"
                mock_temp.return_value = mock_file

                tts = TextToSpeech()
                result = tts.speak("Привет")

                assert result is not None
                mock_tts.save.assert_called_once()

    @patch("lib.tts.TextToSpeech._speak_sapi")
    @patch("lib.tts.TextToSpeech._speak_piper")
    @patch("lib.synth.tts_engines.gTTS")
    def test_speak_falls_back_to_piper_on_gtts_error(
            self, mock_gtts, mock_piper, mock_sapi, capsys):
        mock_gtts.side_effect = Exception("API Error")
        mock_piper.return_value = "/tmp/fallback.wav"

        tts = TextToSpeech()
        result = tts.speak("Привет")

        assert result == "/tmp/fallback.wav"
        assert tts._offline is True
        mock_sapi.assert_not_called()

    @patch("lib.tts.TextToSpeech._speak_sapi")
    @patch("lib.tts.TextToSpeech._speak_piper")
    @patch("lib.synth.tts_engines.gTTS")
    def test_speak_falls_back_to_sapi_when_piper_fails(
            self, mock_gtts, mock_piper, mock_sapi, capsys):
        mock_gtts.side_effect = Exception("API Error")
        mock_piper.return_value = None
        mock_sapi.return_value = "/tmp/sapi.wav"

        tts = TextToSpeech()
        result = tts.speak("Привет")

        assert result == "/tmp/sapi.wav"

    @patch("lib.tts.TextToSpeech._speak_gtts")
    @patch("lib.tts.TextToSpeech._speak_piper")
    def test_speak_skips_gtts_when_offline(self, mock_piper, mock_gtts):
        mock_piper.return_value = "/tmp/p.wav"
        tts = TextToSpeech()
        tts._offline = True

        result = tts.speak("Привет")

        mock_gtts.assert_not_called()
        assert result == "/tmp/p.wav"

    @patch("lib.synth.tts_engines.gTTS")
    def test_speak_gtts_timeout_passed_to_constructor(self, mock_gtts, capsys):
        mock_tts = MagicMock()
        mock_gtts.return_value = mock_tts
        with patch("lib.synth.tts_engines.tempfile.NamedTemporaryFile") as mock_temp:
            mock_file = MagicMock()
            mock_file.name = "test.mp3"
            mock_temp.return_value = mock_file

            tts = TextToSpeech(gtts_timeout=5.0)
            result = tts.speak("Привет")

            assert result == "test.mp3"
            assert mock_gtts.call_args.kwargs["timeout"] == 5.0

    @patch("lib.synth.tts_playback.subprocess.Popen")
    def test_play_wav_uses_soundplayer(self, mock_popen):
        tts = TextToSpeech()
        proc = MagicMock()
        proc.poll.return_value = 0
        proc.returncode = 0
        mock_popen.return_value = proc
        tts._play_wav(r"C:\tmp\audio.wav")

        cmd = mock_popen.call_args.args[0]
        assert cmd[0] == "powershell"
        assert "SoundPlayer" in cmd[-1]

    @patch("lib.synth.tts_playback.subprocess.Popen")
    @patch("lib.synth.tts_engines.gTTS")
    def test_speak_and_play_with_mpg123(self, mock_gtts, mock_popen, capsys):
        mock_tts = MagicMock()
        mock_gtts.return_value = mock_tts

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("lib.synth.tts_engines.tempfile.NamedTemporaryFile") as mock_temp:
                mock_file = MagicMock()
                mock_file.name = f"{tmpdir}/test.mp3"
                mock_temp.return_value = mock_file

                proc = MagicMock()
                proc.poll.return_value = 0
                proc.returncode = 0
                mock_popen.return_value = proc

                tts = TextToSpeech()
                tts.speak_and_play("Готово")

                assert mock_popen.called
                assert mock_popen.call_args.args[0][0] == "mpg123"

    @patch("lib.synth.tts_playback.subprocess.Popen")
    @patch("lib.synth.tts_engines.gTTS")
    def test_speak_and_play_fallback_ffplay(self, mock_gtts, mock_popen, capsys):
        mock_tts = MagicMock()
        mock_gtts.return_value = mock_tts

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("lib.synth.tts_engines.tempfile.NamedTemporaryFile") as mock_temp:
                mock_file = MagicMock()
                mock_file.name = f"{tmpdir}/test.mp3"
                mock_temp.return_value = mock_file

                def popen_side_effect(cmd, *args, **kwargs):
                    if cmd[0] == "mpg123":
                        raise FileNotFoundError()
                    proc = MagicMock()
                    proc.poll.return_value = 0
                    proc.returncode = 0
                    return proc

                mock_popen.side_effect = popen_side_effect

                tts = TextToSpeech()
                tts.speak_and_play("Готово")

                calls = [c.args[0][0] for c in mock_popen.call_args_list]
                assert "mpg123" in calls or "ffplay" in calls

    def test_speak_and_play_no_audio(self, capsys):
        tts = TextToSpeech()
        tts.speak_and_play("")
        captured = capsys.readouterr()
        assert "Пустой текст" in captured.out
