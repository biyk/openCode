"""Тесты TextToSpeech: нарезка фраз и конвейер воспроизведения."""


import time
from unittest.mock import patch
from lib.tts import TextToSpeech


class TestTtsPipeline:
    """split_sentences и порядок проигрывания файлов."""

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

        def fake_speak(text, abort_event=None):
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
