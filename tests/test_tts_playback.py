"""Тесты TextToSpeech: SAPI, файлы, плееры, run_player."""


import os
import subprocess
import threading
from unittest.mock import patch, MagicMock
import pytest
from lib.tts import TextToSpeech


class TestTtsPlayback:
    """SAPI-скрипт, удаление файлов, таймауты плеера."""

    def test_speak_sapi_script_missing(self):
        """Если скрипта SAPI нет — возвращается None."""
        tts = TextToSpeech()
        script = MagicMock()
        script.exists.return_value = False
        with patch("lib.tts_playback._SAPI_SCRIPT", script):
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

        with patch("lib.tts_playback._SAPI_SCRIPT", script):
            with patch("lib.tts_playback.subprocess.run", side_effect=fake_run):
                result = tts._speak_sapi("Привет")
        assert result is not None
        os.unlink(result)

    def test_speak_sapi_empty_output(self):
        """Пустой аудиофайл от SAPI — None и удаление файла."""
        tts = TextToSpeech()
        script = MagicMock()
        script.exists.return_value = True
        with patch("lib.tts_playback._SAPI_SCRIPT", script):
            with patch("lib.tts_playback.subprocess.run"):
                result = tts._speak_sapi("Привет")
        assert result is None

    def test_speak_sapi_error(self):
        """Ошибка SAPI — None и удаление временного файла."""
        tts = TextToSpeech()
        script = MagicMock()
        script.exists.return_value = True
        with patch("lib.tts_playback._SAPI_SCRIPT", script):
            with patch("lib.tts_playback.subprocess.run",
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
        with patch("lib.tts_playback.os.unlink", side_effect=OSError("файл занят")):
            tts._play_file(path)
        tts._play_mp3.assert_called_once_with(path, None)

    @patch("lib.tts_playback.subprocess.Popen")
    def test_play_wav_timeout(self, mock_popen, capsys):
        """Таймаут воспроизведения WAV обрабатывается."""
        proc = MagicMock()
        proc.poll.return_value = None
        mock_popen.return_value = proc
        with patch("lib.tts_playback.time.time", side_effect=[0, 0, 1000]):
            tts = TextToSpeech()
            tts._play_wav(r"C:\tmp\a.wav")
        captured = capsys.readouterr()
        assert "Таймаут" in captured.out
        proc.terminate.assert_called()

    @patch("lib.tts_playback.subprocess.Popen", side_effect=Exception("boom"))
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

        with patch("lib.tts_playback.subprocess.Popen", side_effect=fake_popen):
            tts._play_mp3(r"C:\tmp\a.mp3")
        captured = capsys.readouterr()
        assert "ffplay не найден" in captured.out

    @patch("lib.tts_playback.subprocess.Popen")
    def test_run_player_normal_completion(self, mock_popen):
        """Нормальное завершение плеера возвращает True."""
        tts = TextToSpeech()
        proc = MagicMock()
        proc.poll.return_value = 0
        proc.returncode = 0
        mock_popen.return_value = proc
        assert tts._run_player(["mpg123", "-q", "x"]) is True

    @patch("lib.tts_playback.subprocess.Popen")
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

    @patch("lib.tts_playback.subprocess.Popen")
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
