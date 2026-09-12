import builtins
import queue
import sys
import types
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import main

from lib.orchestrator import Orchestrator


class TestEnsureVoskModel:
    """Тесты для функции ensure_vosk_model."""

    def test_model_already_present(self, monkeypatch, tmp_path):
        """Готовая модель возвращается без скачивания."""
        model_dir = tmp_path / "vosk-model-small-ru-0.22"
        (model_dir / "am").mkdir(parents=True)
        (model_dir / "am" / "final.mdl").write_text("")
        monkeypatch.setattr(main, "MODELS_DIR", str(tmp_path))
        assert main.ensure_vosk_model("ru") == str(model_dir)

    def test_downloads_and_extracts_model(self, monkeypatch, tmp_path):
        """Модель скачивается и распаковывается."""
        monkeypatch.setattr(main, "MODELS_DIR", str(tmp_path))
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("vosk-model-small-ru-0.22/am/final.mdl", "x")
        zip_bytes = buf.getvalue()
        zip_path = str(tmp_path / "vosk-model-small-ru-0.22.zip")

        def fake_get(url, **kwargs):
            Path(zip_path).write_bytes(zip_bytes)
            resp = MagicMock()
            resp.__enter__.return_value = resp
            resp.iter_content.return_value = [zip_bytes]
            return resp

        monkeypatch.setattr(main.requests, "get", fake_get)
        result = main.ensure_vosk_model("ru")
        assert "vosk-model-small-ru-0.22" in result

    def test_download_failure_raises_runtime_error(self, monkeypatch, tmp_path):
        """Ошибка загрузки вызывает RuntimeError."""
        monkeypatch.setattr(main, "MODELS_DIR", str(tmp_path))

        def boom(*args, **kwargs):
            raise OSError("network down")

        monkeypatch.setattr(main.requests, "get", boom)
        with pytest.raises(RuntimeError):
            main.ensure_vosk_model("ru")

    def test_unknown_language_raises_key_error(self, monkeypatch, tmp_path):
        """Неизвестный код языка даёт KeyError."""
        monkeypatch.setattr(main, "MODELS_DIR", str(tmp_path))
        with pytest.raises(KeyError):
            main.ensure_vosk_model("xx")


class TestTranscriptionWorker:
    """Тесты для класса TranscriptionWorker."""

    def _make_worker(self, mocker):
        """Создаёт worker без вызова __init__ (без сети и файлов)."""
        worker = main.TranscriptionWorker.__new__(main.TranscriptionWorker)
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
        return worker

    def test_init_sets_up_components(self, mocker):
        """__init__ собирает матчер, логгер и LLM из конфига."""
        mocker.patch("main.get_device_commands_path", return_value="x")
        mocker.patch("main.CommandMatcher")
        mocker.patch("main.Logger")
        mocker.patch("main.TextToSpeech")
        mock_provider = mocker.patch("main._provider_manager")
        mock_provider.get_client.return_value = "LLM"
        matcher = main.CommandMatcher.return_value
        matcher.get_llm_config.return_value = {"history_limit": 5}

        worker = main.TranscriptionWorker(lang_code="ru", device_name="dev")

        assert worker.lang_code == "ru"
        assert worker._llm == "LLM"
        assert isinstance(worker._orchestrator, Orchestrator)
        mock_provider.get_client.assert_called_once_with(history_limit=5)

    def test_init_default_history_limit(self, mocker):
        """Если history_limit нет в конфиге — используется 10."""
        mocker.patch("main.get_device_commands_path", return_value="x")
        mocker.patch("main.CommandMatcher")
        mocker.patch("main.Logger")
        mocker.patch("main.TextToSpeech")
        mock_provider = mocker.patch("main._provider_manager")
        mock_provider.get_client.return_value = "LLM"
        matcher = main.CommandMatcher.return_value
        matcher.get_llm_config.return_value = {}

        worker = main.TranscriptionWorker()

        assert worker._llm == "LLM"
        mock_provider.get_client.assert_called_once_with(history_limit=10)

    def test_audio_callback_status_does_not_block(self, mocker):
        """Наличие status не мешает постановке данных в очередь."""
        worker = self._make_worker(mocker)
        worker.audio_callback(b"data", 0, None, "error")
        worker._queue.put.assert_called_once_with(b"data")

    def test_audio_callback_queues_data(self, mocker):
        """Обычный блок аудио кладётся в очередь."""
        worker = self._make_worker(mocker)
        worker.audio_callback(b"data", 0, None, None)
        worker._queue.put.assert_called_once_with(b"data")

    def test_stop_clears_running_and_aborts(self, mocker):
        """stop() сбрасывает флаг _running и прерывает озвучку."""
        worker = self._make_worker(mocker)
        worker.stop()
        worker._running.clear.assert_called_once()
        worker._orchestrator.stop.assert_called_once()

    def test_process_text_delegates_to_orchestrator(self, mocker):
        """_process_text передоверяет текст оркестратору."""
        worker = self._make_worker(mocker)
        worker._process_text("пожалуйста что-то")
        worker._orchestrator.process_text.assert_called_once_with(
            "пожалуйста что-то")

    def _patch_run_deps(self, mocker, recognizer=None):
        """Патчит зависимости run() и возвращает recognizer."""
        mocker.patch("main.SetLogLevel")
        mocker.patch("main.ensure_vosk_model", return_value="model")
        mocker.patch("main.Model")
        default_recognizer = mocker.MagicMock()
        mocker.patch(
            "main.KaldiRecognizer", return_value=recognizer or default_recognizer
        )
        mocker.patch("main.sd.RawInputStream", return_value=mocker.MagicMock())
        return recognizer or default_recognizer

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
        mocker.patch("main.ensure_vosk_model", side_effect=RuntimeError("boom"))

        worker.run()

        worker._output.print_error.assert_called_once()
        worker._output.print_stopped.assert_called_once()


class TestMainEntryPoint:
    """Тесты для main() и запуска модуля как __main__."""

    def test_guard_executes_main(self, monkeypatch):
        """Модуль при запуске как __main__ вызывает main()."""
        calls = []

        def _stub(**attrs):
            mod = types.ModuleType("stub")
            mod.__path__ = []
            for key, value in attrs.items():
                setattr(mod, key, value)
            return mod

        class StubOutput:
            def print_text(self, text, **kwargs):
                calls.append(("text", text))

            def print_info(self, text, **kwargs):
                calls.append(("info", text))

            def print_error(self, text, **kwargs):
                calls.append(("error", text))

            def print_progress(self, *args, **kwargs):
                pass

            def print_partial(self, *args, **kwargs):
                pass

            def print_stopped(self):
                calls.append(("stopped",))

        class StubMatcher:
            def __init__(self, *args, **kwargs):
                pass

            def get_llm_config(self):
                return {}

            def has_trigger(self, *args, **kwargs):
                return False

            def find(self, *args, **kwargs):
                return None

            def execute(self, *args, **kwargs):
                pass

            def reload(self):
                pass

        class StubLogger:
            def __init__(self, *args, **kwargs):
                pass

            def log_command(self, *args, **kwargs):
                pass

            def log_llm(self, *args, **kwargs):
                pass

            def get_llm_history(self, *args, **kwargs):
                return []

        class StubTTS:
            def __init__(self, *args, **kwargs):
                pass

            def speak_and_play(self, *args, **kwargs):
                pass

        class StubLLM:
            def ask(self, text):
                return None

        class StubProviderManager:
            def __init__(self, *args, **kwargs):
                pass

            def get_client(self, **kwargs):
                return StubLLM()

        class StubStream:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def raise_on_get(*args, **kwargs):
            raise RuntimeError("stub network")

        monkeypatch.setitem(sys.modules, "lib.output", _stub(TranscriptionOutput=StubOutput))
        monkeypatch.setitem(
            sys.modules, "lib.commands", _stub(CommandMatcher=StubMatcher)
        )
        monkeypatch.setitem(sys.modules, "lib.logger", _stub(Logger=StubLogger))
        monkeypatch.setitem(sys.modules, "lib.tts", _stub(TextToSpeech=StubTTS))
        monkeypatch.setitem(sys.modules, "lib.providers", _stub())
        monkeypatch.setitem(
            sys.modules,
            "lib.config_loader",
            _stub(get_device_commands_path=lambda *a, **k: "commands.json"),
        )
        monkeypatch.setitem(
            sys.modules, "lib.providers.manager",
            _stub(ProviderManager=StubProviderManager),
        )
        monkeypatch.setitem(
            sys.modules, "sounddevice", _stub(RawInputStream=lambda **kw: StubStream())
        )
        monkeypatch.setitem(
            sys.modules,
            "vosk",
            _stub(
                Model=lambda *a: object(),
                KaldiRecognizer=lambda *a: MagicMock(),
                SetLogLevel=lambda *a: None,
            ),
        )
        monkeypatch.setitem(sys.modules, "requests", _stub(get=raise_on_get))

        builtins_dict = dict(vars(builtins))
        builtins_dict["input"] = lambda prompt=None: ""
        source = Path(main.__file__).read_text(encoding="utf-8")

        exec(compile(source, main.__file__, "exec"), {
            "__name__": "__main__",
            "__file__": main.__file__,
            "__builtins__": builtins_dict,
        })

        assert ("stopped",) in calls
        infos = [c[0] for c in calls if c[0] == "info"]
        assert len(infos) >= 2
