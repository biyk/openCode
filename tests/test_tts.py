import pytest
import tempfile
from unittest.mock import patch, MagicMock
from lib.tts import TextToSpeech


class TestTextToSpeech:
    """Тесты для класса TextToSpeech."""

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

    @patch("lib.tts.gTTS")
    def test_speak_success(self, mock_gtts, capsys):
        mock_tts = MagicMock()
        mock_gtts.return_value = mock_tts

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("lib.tts.tempfile.NamedTemporaryFile") as mock_temp:
                mock_file = MagicMock()
                mock_file.name = f"{tmpdir}/test.mp3"
                mock_temp.return_value = mock_file

                tts = TextToSpeech()
                result = tts.speak("Привет")

                assert result is not None
                mock_tts.save.assert_called_once()

    @patch("lib.tts.gTTS")
    def test_speak_handles_exception(self, mock_gtts, capsys):
        mock_gtts.side_effect = Exception("API Error")

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("lib.tts.tempfile.NamedTemporaryFile") as mock_temp:
                mock_file = MagicMock()
                mock_file.name = f"{tmpdir}/test.mp3"
                mock_temp.return_value = mock_file

                tts = TextToSpeech()
                result = tts.speak("Привет")

                assert result is None

    @patch("subprocess.run")
    @patch("lib.tts.gTTS")
    def test_speak_and_play_with_mpg123(self, mock_gtts, mock_run, capsys):
        mock_tts = MagicMock()
        mock_gtts.return_value = mock_tts

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("lib.tts.tempfile.NamedTemporaryFile") as mock_temp:
                mock_file = MagicMock()
                mock_file.name = f"{tmpdir}/test.mp3"
                mock_temp.return_value = mock_file

                mock_run.return_value = MagicMock()

                tts = TextToSpeech()
                tts.speak_and_play("Готово")

                assert mock_run.called

    @patch("subprocess.run")
    @patch("lib.tts.gTTS")
    def test_speak_and_play_fallback_ffplay(self, mock_gtts, mock_run, capsys):
        mock_tts = MagicMock()
        mock_gtts.return_value = mock_tts

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("lib.tts.tempfile.NamedTemporaryFile") as mock_temp:
                mock_file = MagicMock()
                mock_file.name = f"{tmpdir}/test.mp3"
                mock_temp.return_value = mock_file

                def run_side_effect(cmd, *args, **kwargs):
                    if cmd[0] == "mpg123":
                        raise FileNotFoundError()

                mock_run.side_effect = run_side_effect

                tts = TextToSpeech()
                tts.speak_and_play("Готово")

                calls = [c.args[0][0] for c in mock_run.call_args_list]
                assert "mpg123" in calls or "ffplay" in calls

    def test_speak_and_play_no_audio(self, capsys):
        tts = TextToSpeech()
        tts.speak_and_play("")
        captured = capsys.readouterr()
        assert "отменено" in captured.out or "mpg123" in captured.out or "ffplay" in captured.out
