"""Регресс на «наушники выключились — ассистент оглох» и на заглушение их звука.

Проверяет ровно то, чего не делал старый код: вход выбирался один раз при
старте `run()`, поток больше не пересобирался, и после разрыва наушников
Vosk писал тишину с мёртвого микрофона гарнитуры. И обратный случай — что
микрофон гарнитуры сам по себе не открывается: с ним гарнитура уходит в
режим разговора и её стерео-звук молчит.
"""
import queue

import lib.stt.mic_stream as mic_mod
import lib.stt.transcription_worker as worker_mod
from lib.stt.mic_stream import MicWatcher

HEADSET = (12, "Головной телефон (…;(soundcore H30i))")
LAPTOP = (1, "Микрофон (Realtek(R) Audio)")
USB = (3, "Микрофон (USB Audio Device)")


class FakeRunning:
    """`is_set()` истинно ровно N итераций, потом цикл выходит."""

    def __init__(self, iterations):
        self._left = iterations

    def is_set(self):
        if self._left <= 0:
            return False
        self._left -= 1
        return True

    def set(self):
        pass

    def clear(self):
        self._left = 0


def make_worker(mocker, devices=None, connected=None, headset_mic=False):
    """Каркас worker'а без __init__ с настоящим наблюдателем микрофона.

    `devices` и `connected` — мутабельные подставки: тест меняет их посреди
    прогона, как человек, вынимающий штекер или снимающий гарнитуру.
    """
    worker = worker_mod.TranscriptionWorker.__new__(
        worker_mod.TranscriptionWorker)
    worker.lang_code = "ru"
    worker._queue = queue.Queue()
    worker._accumulated = []
    worker._output = mocker.MagicMock()
    worker._logger = mocker.MagicMock()
    worker._orchestrator = mocker.MagicMock()
    worker._orchestrator.speaking = False
    worker._gate = None
    worker._mic = MicWatcher(
        headphone="soundcore H30i", laptop="realtek", poll_s=0.0,
        headset_mic=headset_mic,
        headset_active=lambda: (None if connected is None
                                else connected["on"]),
        devices=lambda: list(devices if devices is not None
                             else [LAPTOP, HEADSET]),
        default_index=lambda: LAPTOP[0])
    return worker


def _patch_env(mocker, rec):
    """Глушит Vosk; возвращает фабрику потоков sounddevice."""
    mocker.patch.object(worker_mod, "SetLogLevel")
    mocker.patch("lib.stt.vosk_model.ensure_vosk_model", return_value="model")
    mocker.patch.object(worker_mod, "Model")
    mocker.patch.object(worker_mod, "KaldiRecognizer", return_value=rec)
    streams = []

    def make_stream(**kwargs):
        stream = mocker.MagicMock()
        stream.kwargs = kwargs
        streams.append(stream)
        return stream

    mocker.patch.object(mic_mod.sd, "RawInputStream", side_effect=make_stream)
    return streams


def _recognizer(mocker):
    rec = mocker.MagicMock()
    rec.AcceptWaveform.return_value = False
    rec.PartialResult.return_value = '{"partial": ""}'
    rec.FinalResult.return_value = '{"text": ""}'
    return rec


def devices_of(streams):
    """Какие индексы устройств worker открывал, по порядку."""
    return [s.kwargs["device"] for s in streams]


def flip_and_empties(worker, connected):
    """Меняет флаг гарнитуры на первой же строке цикла, дальше тишина."""
    def get(timeout=0.2):
        connected["on"] = not connected["on"]
        raise queue.Empty

    worker._queue.get = get


class TestMicSwitchInRunLoop:
    """run() пересобирает поток захвата вслед за сменой микрофона."""

    def test_connected_headphones_do_not_steal_the_mic(self, mocker):
        """Баг пользователя: как только worker брал BT-микрофон, в наушниках
        не было слышно ничего — гарнитура уходила в режим разговора."""
        worker = make_worker(mocker, connected={"on": True})
        worker._running = FakeRunning(1)
        streams = _patch_env(mocker, _recognizer(mocker))
        worker.run()
        assert devices_of(streams) == [LAPTOP[0]]

    def test_laptop_input_vanishing_reopens_the_stream(self, mocker):
        """Вынули микрофон — поток пересобирается на оставшийся и сброс слова."""
        devices = [LAPTOP, USB]
        worker = make_worker(mocker, devices=devices)
        worker._running = FakeRunning(3)
        rec = _recognizer(mocker)
        streams = _patch_env(mocker, rec)

        def drop_then_empty(timeout=0.2):
            devices.remove(LAPTOP)
            raise queue.Empty

        worker._queue.get = drop_then_empty
        worker.run()
        assert devices_of(streams) == [LAPTOP[0], USB[0]]
        streams[-1].start.assert_called_once_with()
        streams[0].stop.assert_called_once_with()
        rec.Reset.assert_called()

    def test_headset_mic_switches_when_explicitly_allowed(self, mocker):
        """`mic.headset_mic: true` возвращает слежение за гарнитурой."""
        connected = {"on": True}
        worker = make_worker(mocker, connected=connected, headset_mic=True)
        worker._running = FakeRunning(3)
        streams = _patch_env(mocker, _recognizer(mocker))
        flip_and_empties(worker, connected)
        worker.run()
        assert devices_of(streams)[0] == HEADSET[0]
        assert LAPTOP[0] in devices_of(streams)

    def test_run_closes_stream_on_exit(self, mocker):
        """Выход из цикла гасит поток (иначе устройство занято навечно)."""
        worker = make_worker(mocker, connected={"on": False})
        worker._running = FakeRunning(1)
        streams = _patch_env(mocker, _recognizer(mocker))
        worker.run()
        assert streams[0].stop.called and streams[0].close.called
