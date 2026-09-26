"""Тесты TranscriptionWorker.run: обработка очереди аудио."""


import queue
import lib.stt.transcription_worker


class TestTranscriptionWorkerRun:
    """AcceptWaveform, финал, частичные результаты."""

    def _make_worker(self, mocker):
        """Создаёт worker без вызова __init__ (без сети и файлов)."""
        cls = lib.stt.transcription_worker.TranscriptionWorker
        worker = cls.__new__(cls)
        worker.lang_code = "ru"
        worker._running = mocker.MagicMock()
        worker._queue = mocker.MagicMock()
        worker._accumulated = []
        worker._output = mocker.MagicMock()
        worker._logger = mocker.MagicMock()
        worker._matcher = mocker.MagicMock()
        worker._llm = mocker.MagicMock()
        worker._tts = mocker.MagicMock()
        worker._orchestrator = mocker.MagicMock()
        worker._orchestrator.speaking = False
        return worker

    def _patch_run_deps(self, mocker, recognizer=None, stop_recognizer=None):
        """Патчит зависимости run() и возвращает recognizer."""
        mocker.patch("lib.stt.transcription_worker._fix_encoding", side_effect=lambda x: x)
        mocker.patch("lib.stt.transcription_worker.SetLogLevel")
        mocker.patch("lib.stt.vosk_model.ensure_vosk_model", return_value="model")
        mocker.patch("lib.stt.transcription_worker.Model")
        default_recognizer = mocker.MagicMock()
        main_recognizer = recognizer or default_recognizer
        default_stop = mocker.MagicMock()
        default_stop.AcceptWaveform.return_value = False
        stop_rec = stop_recognizer or default_stop

        def _make_recognizer(model, rate, grammar=None):
            if grammar is None:
                return main_recognizer
            return stop_rec

        mocker.patch("lib.stt.transcription_worker.KaldiRecognizer", side_effect=_make_recognizer)
        mocker.patch(
            "lib.stt.transcription_worker.sd.RawInputStream",
            return_value=mocker.MagicMock())
        return main_recognizer

    def test_run_processes_audio_queue(self, mocker):
        """run() распознаёт блоки аудио и обрабатывает текст."""
        worker = self._make_worker(mocker)
        worker._running.is_set.side_effect = [True, True, False]
        worker._queue.get.side_effect = [b"audio", queue.Empty]
        recognizer = self._patch_run_deps(mocker)
        recognizer.AcceptWaveform.return_value = True
        recognizer.Result.return_value = '{"text": "привет"}'
        recognizer.FinalResult.return_value = '{"text": ""}'
        worker._matcher.has_trigger.return_value = False

        worker.run()

        assert worker._accumulated == ["привет"]
        worker._logger.log_command.assert_called_once_with("привет")
        worker._output.print_stopped.assert_called_once()

    def test_run_empty_text_skipped(self, mocker):
        """Пустой распознанный текст не обрабатывается."""
        worker = self._make_worker(mocker)
        worker._running.is_set.side_effect = [True, False]
        worker._queue.get.return_value = b"audio"
        recognizer = self._patch_run_deps(mocker)
        recognizer.AcceptWaveform.return_value = True
        recognizer.Result.return_value = '{"text": ""}'
        recognizer.FinalResult.return_value = '{"text": ""}'
        worker._matcher.has_trigger.return_value = False

        worker.run()

        assert worker._accumulated == []
        worker._output.print_stopped.assert_called_once()

    def test_run_accept_waveform_false_processes_final(self, mocker):
        """При False от AcceptWaveform обрабатывается финальный текст."""
        worker = self._make_worker(mocker)
        worker._running.is_set.side_effect = [True, False]
        worker._queue.get.return_value = b"audio"
        recognizer = self._patch_run_deps(mocker)
        recognizer.AcceptWaveform.return_value = False
        recognizer.PartialResult.return_value = '{"partial": ""}'
        recognizer.FinalResult.return_value = '{"text": "финал"}'
        worker._matcher.has_trigger.return_value = False

        worker.run()

        assert worker._accumulated == ["финал"]
        worker._output.print_stopped.assert_called_once()

    def test_run_aborts_on_partial_stop_word(self, mocker):
        """Стоп-слово в частичном результате прерывает озвучку и сбрасывает Vosk."""
        worker = self._make_worker(mocker)
        worker._running.is_set.side_effect = [True, False]
        worker._queue.get.return_value = b"audio"
        recognizer = self._patch_run_deps(mocker)
        recognizer.AcceptWaveform.return_value = False
        recognizer.PartialResult.return_value = '{"partial": "сделай стоп"}'
        worker._orchestrator.maybe_abort.return_value = True

        worker.run()

        worker._orchestrator.maybe_abort.assert_called_once_with(
            "сделай стоп")
        recognizer.Reset.assert_called_once()

    def test_run_partial_result_without_stop_word(self, mocker):
        """Частичный результат без стоп-слова не прерывает озвучку."""
        worker = self._make_worker(mocker)
        worker._running.is_set.side_effect = [True, False]
        worker._queue.get.return_value = b"audio"
        recognizer = self._patch_run_deps(mocker)
        recognizer.AcceptWaveform.return_value = False
        recognizer.PartialResult.return_value = '{"partial": "проверка"}'
        worker._orchestrator.maybe_abort.return_value = False

        worker.run()

        worker._orchestrator.maybe_abort.assert_called_once_with(
            "проверка")
        recognizer.Reset.assert_not_called()
        worker._output.print_stopped.assert_called_once()
