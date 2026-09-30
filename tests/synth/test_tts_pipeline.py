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


class TestSpeakBlocks:
    """speak_blocks: блоки без перерезки, порядок, кэш прячет генерацию."""

    @patch("lib.tts.TextToSpeech._play_file")
    @patch("lib.tts.TextToSpeech.speak")
    def test_blocks_passed_verbatim_no_resplit(self, mock_speak, mock_play):
        seen = []

        def sp(text, abort_event=None):
            seen.append(text)
            return f"/tmp/{len(seen)}.mp3"

        mock_speak.side_effect = sp
        blocks = ["Раз, два, три.", "четыре; пять"]
        TextToSpeech(max_workers=2).speak_blocks(blocks)
        assert seen == blocks

    @patch("lib.tts.TextToSpeech._play_file")
    @patch("lib.tts.TextToSpeech.speak")
    def test_blocks_played_in_order(self, mock_speak, mock_play):
        blocks = ["A.", "B.", "C."]
        paths = ["/tmp/a.mp3", "/tmp/b.mp3", "/tmp/c.mp3"]
        mock_speak.side_effect = (
            lambda t, abort_event=None: paths[blocks.index(t)])
        TextToSpeech(max_workers=3).speak_blocks(blocks)
        played = [c.args[0] for c in mock_play.call_args_list]
        assert played == paths

    @patch("lib.tts.TextToSpeech._play_file")
    @patch("lib.tts.TextToSpeech.speak")
    def test_single_block(self, mock_speak, mock_play):
        mock_speak.return_value = "/tmp/s.mp3"
        TextToSpeech().speak_blocks(["  Готово  "])
        mock_speak.assert_called_once_with("Готово", None)
        mock_play.assert_called_once_with("/tmp/s.mp3", None)

    @patch("lib.tts.TextToSpeech.speak")
    def test_empty_blocks(self, mock_speak, capsys):
        done = []
        TextToSpeech().speak_blocks(["", "   "], on_finished=lambda: done.append(1))
        assert "Пустой текст" in capsys.readouterr().out
        assert done == [1]
        mock_speak.assert_not_called()

    @patch("lib.tts.TextToSpeech._play_file")
    @patch("lib.tts.TextToSpeech.speak")
    def test_speak_and_play_delegates(self, mock_speak, mock_play):
        mock_speak.side_effect = (
            lambda t, abort_event=None: f"/tmp/{t}.mp3")
        TextToSpeech(max_workers=2).speak_and_play("Первое. Второе.")
        spoken = {c.args[0] for c in mock_speak.call_args_list}
        assert spoken == {"Первое.", "Второе."}

    def test_cached_frame_plays_while_new_name_generates(self, tmp_path, monkeypatch):
        """Кэшированный фрейм не идёт в сеть — генерится только новое имя."""
        from pathlib import Path
        from lib.synth import tts_cache

        monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path / "mp3")
        frame = "Задача выполнена."
        seed = Path(tts_cache.tempfile.mkstemp(suffix=".mp3")[1])
        seed.write_bytes(b"ID3")
        tts_cache.store("ru", frame, str(seed))

        gen = []

        class FakeG:
            def __init__(self, **kwargs):
                pass

            def save(self, p):
                gen.append(p)
                Path(p).write_bytes(b"ID3name")

        monkeypatch.setattr("lib.synth.tts_engines.gTTS", FakeG)
        played = []
        tts = TextToSpeech()
        monkeypatch.setattr(tts, "_play_file",
                            lambda p, a=None: played.append(p))

        tts.speak_blocks([frame, "Отчёт."])

        assert len(gen) == 1            # сеть — только для нового названия
        assert len(played) == 2         # оба блока сыграны по порядку
