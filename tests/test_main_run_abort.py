"""Тесты TranscriptionWorker.run: стоп-слова и ошибки."""


import queue
import lib.transcription_worker


class TestTranscriptionWorkerRunAbort:
    """Stop-детектор, пустая очередь, исключения."""

    def _make_worker(self, mocker):
        """Создаёт worker без вызова __init__ (без сети и файлов)."""
        cls = lib.transcription_worker.TranscriptionWorker
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
        mocker.patch("lib.transcription_worker._fix_encoding", side_effect=lambda x: x)
        mocker.patch("lib.transcription_worker.SetLogLevel")
        mocker.patch("lib.vosk_model.ensure_vosk_model", return_value="model")
        mocker.patch("lib.transcription_worker.Model")
        default_recognizer = mocker.MagicMock()
        main_recognizer = recognizer or default_recognizer
        default_stop = mocker.MagicMock()
        default_stop.AcceptWaveform.return_value = False
        stop_rec = stop_recognizer or default_stop

        def _make_recognizer(model, rate, grammar=None):
            if grammar is None:
                return main_recognizer
            return stop_rec

        mocker.patch("lib.transcription_worker.KaldiRecognizer", side_effect=_make_recognizer)
        mocker.patch("lib.transcription_worker.sd.RawInputStream", return_value=mocker.MagicMock())
        return main_recognizer

    def test_run_stop_recognizer_aborts_when_speaking(self, mocker):
        """Грамматический распознаватель стоп-слов прерывает озвучку."""
        worker = self._make_worker(mocker)
        worker._running.is_set.side_effect = [True, False]
        worker._queue.get.return_value = b"audio"
        stop_recognizer = mocker.MagicMock()
        stop_recognizer.AcceptWaveform.return_value = True
        stop_recognizer.Result.return_value = '{"text": "стоп"}'
        recognizer = self._patch_run_deps(
            mocker, stop_recognizer=stop_recognizer)
        recognizer.AcceptWaveform.return_value = False
        recognizer.PartialResult.return_value = '{"partial": ""}'
        worker._orchestrator.speaking = True
        worker._orchestrator.maybe_abort.return_value = True

        worker.run()

        worker._orchestrator.maybe_abort.assert_called_once_with("стоп")
        recognizer.Reset.assert_called_once()
        stop_recognizer.Reset.assert_called_once()
        worker._output.print_stopped.assert_called_once()

    def test_run_stop_recognizer_no_abort_when_text_empty(self, mocker):
        """Пустой стоп-результат не сбрасывает распознаватели."""
        worker = self._make_worker(mocker)
        worker._running.is_set.side_effect = [True, False]
        worker._queue.get.return_value = b"audio"
        stop_recognizer = mocker.MagicMock()
        stop_recognizer.AcceptWaveform.return_value = True
        stop_recognizer.Result.return_value = '{"text": ""}'
        recognizer = self._patch_run_deps(
            mocker, stop_recognizer=stop_recognizer)
        recognizer.AcceptWaveform.return_value = False
        recognizer.PartialResult.return_value = '{"partial": ""}'
        worker._orchestrator.speaking = True

        worker.run()

        worker._orchestrator.maybe_abort.assert_not_called()
        recognizer.Reset.assert_not_called()
        stop_recognizer.Reset.assert_not_called()
        worker._output.print_stopped.assert_called_once()

    def test_run_stop_path_skipped_when_not_speaking(self, mocker):
        """Вне озвучки грамматический распознаватель не используется."""
        worker = self._make_worker(mocker)
        worker._running.is_set.side_effect = [True, False]
        worker._queue.get.return_value = b"audio"
        stop_recognizer = mocker.MagicMock()
        recognizer = self._patch_run_deps(
            mocker, stop_recognizer=stop_recognizer)
        recognizer.AcceptWaveform.return_value = False
        recognizer.PartialResult.return_value = '{"partial": ""}'
        worker._orchestrator.speaking = False

        worker.run()

        stop_recognizer.AcceptWaveform.assert_not_called()
        worker._output.print_stopped.assert_called_once()

    def test_run_queue_empty_continues(self, mocker):
        """Пустая очередь не прерывает цикл."""
        worker = self._make_worker(mocker)
        worker._running.is_set.side_effect = [True, False]
        worker._queue.get.side_effect = queue.Empty
        recognizer = self._patch_run_deps(mocker)
        recognizer.FinalResult.return_value = '{"text": ""}'
        worker._matcher.has_trigger.return_value = False

        worker.run()

        assert worker._accumulated == []
        worker._output.print_stopped.assert_called_once()

    def test_run_prints_error_on_exception(self, mocker):
        """Исключение в run() печатается как ошибка STT."""
        worker = self._make_worker(mocker)
        mocker.patch("lib.vosk_model.ensure_vosk_model", side_effect=RuntimeError("boom"))

        worker.run()

        worker._output.print_error.assert_called_once()
        worker._output.print_stopped.assert_called_once()
        error_msg = worker._output.print_error.call_args[0][0]
        assert "boom" in str(error_msg)
