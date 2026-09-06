import time

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

    @patch("lib.tts.TextToSpeech._speak_sapi")
    @patch("lib.tts.TextToSpeech._speak_piper")
    @patch("lib.tts.gTTS")
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
    @patch("lib.tts.gTTS")
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

    @patch("lib.tts.gTTS")
    def test_speak_gtts_timeout_passed_to_constructor(self, mock_gtts, capsys):
        mock_tts = MagicMock()
        mock_gtts.return_value = mock_tts
        with patch("lib.tts.tempfile.NamedTemporaryFile") as mock_temp:
            mock_file = MagicMock()
            mock_file.name = "test.mp3"
            mock_temp.return_value = mock_file

            tts = TextToSpeech(gtts_timeout=5.0)
            result = tts.speak("Привет")

            assert result == "test.mp3"
            assert mock_gtts.call_args.kwargs["timeout"] == 5.0

    @patch("subprocess.run")
    def test_play_wav_uses_soundplayer(self, mock_run):
        tts = TextToSpeech()
        tts._play_wav(r"C:\tmp\audio.wav")

        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "powershell"
        assert "SoundPlayer" in cmd[-1]

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
        assert "Пустой текст" in captured.out

    def test_split_sentences_preserves_order(self):
        tts = TextToSpeech()
        text = ("Привет! Как твои дела? Сегодня хорошая погода. "
                "Завтра по плану дождь, не забудь зонт.")
        result = tts._split_sentences(text)
        assert result == [
            "Привет!",
            "Как твои дела?",
            "Сегодня хорошая погода.",
            "Завтра по плану дождь,",
            "не забудь зонт.",
        ]

    def test_split_sentences_splits_on_dash_and_semicolon(self):
        tts = TextToSpeech()
        text = "Открой браузер — запусти музыку; проверь почту"
        result = tts._split_sentences(text)
        assert result == ["Открой браузер —", "запусти музыку;", "проверь почту"]

    def test_split_sentences_keeps_compound_words(self):
        tts = TextToSpeech()
        text = "Кто-то во-первых просит это-то"
        assert tts._split_sentences(text) == [text]

    def test_split_sentences_single(self):
        tts = TextToSpeech()
        assert tts._split_sentences("Готово") == ["Готово"]

    def test_split_sentences_empty(self):
        tts = TextToSpeech()
        assert tts._split_sentences("") == [""]

    @patch("lib.tts.TextToSpeech._play_file")
    @patch("lib.tts.TextToSpeech.speak")
    def test_speak_and_play_pipeline_plays_in_order(self, mock_speak, mock_play, capsys):
        sentences = ["Первое предложение.", "Второе предложение.", "Третье предложение."]
        paths = [f"/tmp/{i}.mp3" for i in range(3)]

        def fake_speak(text):
            idx = sentences.index(text)
            if idx == 0:
                time.sleep(0.2)
            return paths[idx]

        mock_speak.side_effect = fake_speak
        tts = TextToSpeech(max_workers=4)
        tts.speak_and_play(" ".join(sentences))

        played = [call.args[0] for call in mock_play.call_args_list]
        assert played == paths
        assert mock_speak.call_count == 3

    @patch("lib.tts.TextToSpeech._play_file")
    @patch("lib.tts.TextToSpeech.speak")
    def test_speak_and_play_pipeline_skips_failed_files(self, mock_speak, mock_play, capsys):
        mock_speak.side_effect = [None, "/tmp/one.mp3"]
        tts = TextToSpeech(max_workers=4)
        tts.speak_and_play("Первое. Второе.")

        played = [call.args[0] for call in mock_play.call_args_list]
        assert played == ["/tmp/one.mp3"]
