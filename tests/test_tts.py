import os
import subprocess
import tempfile
import threading
import time
from unittest.mock import patch, MagicMock

import pytest

from lib.tts import TextToSpeech, _decode_arg, main


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

    def test_speak_abort_returns_none(self, capsys):
        """При установленном abort_event синтез пропускается."""
        tts = TextToSpeech()
        abort = threading.Event()
        abort.set()
        with patch.object(tts, "_speak_gtts") as mock_gtts:
            result = tts.speak("Привет", abort_event=abort)
        assert result is None
        mock_gtts.assert_not_called()

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

    @patch("lib.tts.subprocess.Popen")
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

    @patch("lib.tts.subprocess.Popen")
    @patch("lib.tts.gTTS")
    def test_speak_and_play_with_mpg123(self, mock_gtts, mock_popen, capsys):
        mock_tts = MagicMock()
        mock_gtts.return_value = mock_tts

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("lib.tts.tempfile.NamedTemporaryFile") as mock_temp:
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

    @patch("lib.tts.subprocess.Popen")
    @patch("lib.tts.gTTS")
    def test_speak_and_play_fallback_ffplay(self, mock_gtts, mock_popen, capsys):
        mock_tts = MagicMock()
        mock_gtts.return_value = mock_tts

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("lib.tts.tempfile.NamedTemporaryFile") as mock_temp:
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
        with patch("lib.tts._PIPER_MODEL", model):
            assert tts._get_piper_voice() is None
        assert tts._piper_error is True

    def test_get_piper_voice_success(self):
        """Успешная ленивая загрузка модели Piper."""
        tts = TextToSpeech()
        model = MagicMock()
        model.exists.return_value = True
        voice = MagicMock()
        with patch("lib.tts._PIPER_MODEL", model):
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
        with patch("lib.tts._PIPER_MODEL", model):
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

    def test_speak_sapi_script_missing(self):
        """Если скрипта SAPI нет — возвращается None."""
        tts = TextToSpeech()
        script = MagicMock()
        script.exists.return_value = False
        with patch("lib.tts._SAPI_SCRIPT", script):
            assert tts._speak_sapi("Привет") is None

    def test_speak_sapi_success(self):
        """Успешный синтез через System.Speech."""
        tts = TextToSpeech()
        script = MagicMock()
        script.exists.return_value = True

        def fake_run(cmd, *args, **kwargs):
            outfile = cmd[cmd.index("-OutFile") + 1]
            with open(outfile, "wb") as f:
                f.write(b"WAVDATA")

        with patch("lib.tts._SAPI_SCRIPT", script):
            with patch("lib.tts.subprocess.run", side_effect=fake_run):
                result = tts._speak_sapi("Привет")
        assert result is not None
        os.unlink(result)

    def test_speak_sapi_empty_output(self):
        """Пустой аудиофайл от SAPI — None и удаление файла."""
        tts = TextToSpeech()
        script = MagicMock()
        script.exists.return_value = True
        with patch("lib.tts._SAPI_SCRIPT", script):
            with patch("lib.tts.subprocess.run"):
                result = tts._speak_sapi("Привет")
        assert result is None

    def test_speak_sapi_error(self):
        """Ошибка SAPI — None и удаление временного файла."""
        tts = TextToSpeech()
        script = MagicMock()
        script.exists.return_value = True
        with patch("lib.tts._SAPI_SCRIPT", script):
            with patch("lib.tts.subprocess.run",
                       side_effect=Exception("boom")):
                assert tts._speak_sapi("Привет") is None

    def test_play_file_wav_deletes(self):
        """WAV файл удаляется после воспроизведения."""
        tts = TextToSpeech()
        tts._play_wav = MagicMock()
        path = tts._temp_file(".wav")
        with open(path, "wb") as f:
            f.write(b"RIFF")
        tts._play_file(path)
        assert not os.path.exists(path)
        tts._play_wav.assert_called_once_with(path, None)

    def test_play_file_mp3_deletes(self):
        """MP3 файл удаляется после воспроизведения."""
        tts = TextToSpeech()
        tts._play_mp3 = MagicMock()
        path = tts._temp_file(".mp3")
        with open(path, "wb") as f:
            f.write(b"ID3")
        tts._play_file(path)
        assert not os.path.exists(path)
        tts._play_mp3.assert_called_once_with(path, None)

    def test_play_file_unlink_error_tolerated(self):
        """WinError 32 при удалении занятого файла не роняет поток."""
        tts = TextToSpeech()
        tts._play_mp3 = MagicMock()
        path = tts._temp_file(".mp3")
        with open(path, "wb") as f:
            f.write(b"ID3")
        with patch("lib.tts.os.unlink", side_effect=OSError("файл занят")):
            tts._play_file(path)
        tts._play_mp3.assert_called_once_with(path, None)

    @patch("lib.tts.subprocess.Popen")
    def test_play_wav_timeout(self, mock_popen, capsys):
        """Таймаут воспроизведения WAV обрабатывается."""
        proc = MagicMock()
        proc.poll.return_value = None
        mock_popen.return_value = proc
        with patch("lib.tts.time.time", side_effect=[0, 0, 1000]):
            tts = TextToSpeech()
            tts._play_wav(r"C:\tmp\a.wav")
        captured = capsys.readouterr()
        assert "Таймаут" in captured.out
        proc.terminate.assert_called()

    @patch("lib.tts.subprocess.Popen", side_effect=Exception("boom"))
    def test_play_wav_error(self, mock_popen, capsys):
        """Ошибка воспроизведения WAV обрабатывается."""
        tts = TextToSpeech()
        tts._play_wav(r"C:\tmp\a.wav")

    def test_play_mp3_ffplay_missing(self, capsys):
        """Когда и mpg123 и ffplay отсутствуют — сообщение об ошибке."""
        tts = TextToSpeech()

        def fake_popen(cmd, *args, **kwargs):
            if cmd[0] in ("mpg123", "ffplay"):
                raise FileNotFoundError()
            return MagicMock()

        with patch("lib.tts.subprocess.Popen", side_effect=fake_popen):
            tts._play_mp3(r"C:\tmp\a.mp3")
        captured = capsys.readouterr()
        assert "ffplay не найден" in captured.out

    @patch("lib.tts.subprocess.Popen")
    def test_run_player_normal_completion(self, mock_popen):
        """Нормальное завершение плеера возвращает True."""
        tts = TextToSpeech()
        proc = MagicMock()
        proc.poll.return_value = 0
        proc.returncode = 0
        mock_popen.return_value = proc
        assert tts._run_player(["mpg123", "-q", "x"]) is True

    @patch("lib.tts.subprocess.Popen")
    def test_run_player_abort_terminates(self, mock_popen):
        """abort_event прерывает воспроизведение и возвращает False."""
        tts = TextToSpeech()
        abort = threading.Event()
        abort.set()
        proc = MagicMock()
        proc.poll.return_value = None
        mock_popen.return_value = proc
        assert tts._run_player(["mpg123", "-q", "x"], abort_event=abort) is False
        proc.terminate.assert_called_once()

    @patch("lib.tts.subprocess.Popen")
    def test_run_player_nonzero_exit_raises(self, mock_popen):
        """Ненулевой код возврата плеера даёт CalledProcessError."""
        tts = TextToSpeech()
        proc = MagicMock()
        proc.poll.return_value = 1
        proc.returncode = 1
        mock_popen.return_value = proc
        with pytest.raises(subprocess.CalledProcessError):
            tts._run_player(["mpg123", "-q", "x"])
        proc.terminate.assert_called_once()

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
    """Декодирование аргумента CLI озвучки."""

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
    """CLI: python -m lib.tts."""

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
