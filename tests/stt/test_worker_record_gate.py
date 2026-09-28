"""Шлюз записи в worker'е: кадры не идут в распознаватель, пока шлюз закрыт."""
import json
import queue

import lib.stt.transcription_worker as worker_mod


def make_worker(mocker, gate):
    """Каркас worker'а без __init__ (тот поднимает модели, конфиг и сеть)."""
    worker = worker_mod.TranscriptionWorker.__new__(
        worker_mod.TranscriptionWorker)
    worker.lang_code = "ru"
    worker._queue = mocker.MagicMock()
    worker._accumulated = []
    worker._output = mocker.MagicMock()
    worker._logger = mocker.MagicMock()
    worker._orchestrator = mocker.MagicMock()
    worker._orchestrator.speaking = False
    worker._gate = gate
    return worker


class TestAudioCallbackGate:
    """Колбэк sounddevice: глушение или постановка кадра в очередь."""

    def test_frame_dropped_while_blocked(self, mocker):
        """Закрытый шлюз — ни одного байта в очереди (ассистент глух)."""
        gate = mocker.MagicMock()
        gate.blocked = True
        worker = make_worker(mocker, gate)
        worker.audio_callback(b"data", 2, None, None)
        worker._queue.put.assert_not_called()

    def test_frame_queued_while_open(self, mocker):
        """Открытый шлюз — обычный путь аудио."""
        gate = mocker.MagicMock()
        gate.blocked = False
        worker = make_worker(mocker, gate)
        worker.audio_callback(b"data", 2, None, None)
        worker._queue.put.assert_called_once_with(b"data")

    def test_frame_queued_without_gate(self, mocker):
        """Worker без шлюза (секция выключена) пишет всегда."""
        worker = make_worker(mocker, None)
        worker.audio_callback(b"data", 2, None, None)
        worker._queue.put.assert_called_once_with(b"data")


class TestRunLoopGate:
    """Цикл захвата: поток шлюза и сброс распознавателя на переключении."""

    def _patch_env(self, mocker, rec):
        """Глушит Vosk и микрофон; возвращает mocks sd-потока."""
        mocker.patch.object(worker_mod, "SetLogLevel")
        mocker.patch("lib.stt.vosk_model.ensure_vosk_model",
                     return_value="model")
        mocker.patch.object(worker_mod, "Model")
        mocker.patch.object(worker_mod, "KaldiRecognizer", return_value=rec)
        return mocker.patch("lib.stt.transcription_worker.sd.RawInputStream",
                            return_value=mocker.MagicMock())

    def _make_recognizer(self, mocker):
        """Vosk-мок: один не финальный блок без частичной речи."""
        rec = mocker.MagicMock()
        rec.AcceptWaveform.return_value = False
        rec.PartialResult.return_value = json.dumps({"partial": ""})
        rec.FinalResult.return_value = json.dumps({"text": ""})
        return rec

    def test_run_starts_and_stops_gate(self, mocker):
        """run() поднимает поток опроса, stop() его снимает."""
        gate = mocker.MagicMock()
        gate.blocked = False
        gate.take_change.return_value = False
        worker = make_worker(mocker, gate)
        worker._running = mocker.MagicMock()
        worker._running.is_set.return_value = False
        self._patch_env(mocker, self._make_recognizer(mocker))
        worker.run()
        gate.start.assert_called_once_with()
        worker.stop()
        gate.stop.assert_called_once_with()

    def test_recognizer_reset_after_gate_change(self, mocker):
        """Переключение шлюза — сброс распознавателя (обрывок не команда)."""
        gate = mocker.MagicMock()
        gate.blocked = False
        gate.take_change.side_effect = [True, False]
        worker = make_worker(mocker, gate)
        worker._running = mocker.MagicMock()
        worker._running.is_set.side_effect = [True, False]
        worker._queue = queue.Queue()
        worker._queue.put(b"audio")
        rec = self._make_recognizer(mocker)
        self._patch_env(mocker, rec)
        worker.run()
        rec.Reset.assert_called_once_with()
