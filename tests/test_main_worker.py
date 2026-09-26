"""Тесты TranscriptionWorker: инициализация и колбэки."""


from lib.core.orchestrator import Orchestrator
import lib.stt.transcription_worker


class TestTranscriptionWorkerInit:
    """Сборка компонентов, аудио-колбэки, stop."""

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

    def test_init_sets_up_components(self, mocker):
        """__init__ собирает матчер, логгер и LLM из конфига."""
        mocker.patch("lib.stt.transcription_worker.get_device_commands_path", return_value="x")
        mocker.patch("lib.stt.transcription_worker.CommandMatcher")
        mocker.patch("lib.stt.transcription_worker.Logger")
        mocker.patch("lib.stt.transcription_worker.TextToSpeech")
        mock_provider = mocker.patch("lib.stt.transcription_worker._provider_manager")
        mock_provider.get_client.return_value = "LLM"
        matcher = lib.stt.transcription_worker.CommandMatcher.return_value
        matcher.get_llm_config.return_value = {"history_limit": 5}
        matcher.get_intent_config.return_value = {}

        worker = lib.stt.transcription_worker.TranscriptionWorker(lang_code="ru", device_name="dev")

        assert worker.lang_code == "ru"
        assert worker._llm == "LLM"
        assert isinstance(worker._orchestrator, Orchestrator)
        mock_provider.get_client.assert_called_once_with(history_limit=5)

    def test_init_default_history_limit(self, mocker):
        """Если history_limit нет в конфиге — используется 10."""
        mocker.patch("lib.stt.transcription_worker.get_device_commands_path", return_value="x")
        mocker.patch("lib.stt.transcription_worker.CommandMatcher")
        mocker.patch("lib.stt.transcription_worker.Logger")
        mocker.patch("lib.stt.transcription_worker.TextToSpeech")
        mock_provider = mocker.patch("lib.stt.transcription_worker._provider_manager")
        mock_provider.get_client.return_value = "LLM"
        matcher = lib.stt.transcription_worker.CommandMatcher.return_value
        matcher.get_llm_config.return_value = {}
        matcher.get_intent_config.return_value = {}

        worker = lib.stt.transcription_worker.TranscriptionWorker()

        assert worker._llm == "LLM"
        mock_provider.get_client.assert_called_once_with(history_limit=10)

    def test_init_builds_intent_classifier_when_enabled(self, mocker):
        """При intent.enabled=true создаётся классификатор через build_intent."""
        mocker.patch("lib.stt.transcription_worker.get_device_commands_path", return_value="x")
        mocker.patch("lib.stt.transcription_worker.CommandMatcher")
        mocker.patch("lib.stt.transcription_worker.Logger")
        mocker.patch("lib.stt.transcription_worker.TextToSpeech")
        mock_provider = mocker.patch("lib.stt.transcription_worker._provider_manager")
        mock_provider.get_client.return_value = "LLM"
        matcher = lib.stt.transcription_worker.CommandMatcher.return_value
        matcher.get_llm_config.return_value = {}
        matcher.get_intent_config.return_value = {
            "enabled": True, "include_media": True}
        mock_intent = mocker.patch(
            "lib.stt.transcription_worker.build_intent", return_value="INTENT")

        worker = lib.stt.transcription_worker.TranscriptionWorker()

        mock_intent.assert_called_once_with(matcher, "LLM")
        assert worker._orchestrator._intent == "INTENT"

    def test_init_intent_without_media_probe(self, mocker):
        """include_media=false: build_intent всё равно создаёт классификатор."""
        mocker.patch("lib.stt.transcription_worker.get_device_commands_path", return_value="x")
        mocker.patch("lib.stt.transcription_worker.CommandMatcher")
        mocker.patch("lib.stt.transcription_worker.Logger")
        mocker.patch("lib.stt.transcription_worker.TextToSpeech")
        mock_provider = mocker.patch("lib.stt.transcription_worker._provider_manager")
        mock_provider.get_client.return_value = "LLM"
        matcher = lib.stt.transcription_worker.CommandMatcher.return_value
        matcher.get_llm_config.return_value = {}
        matcher.get_intent_config.return_value = {
            "enabled": True, "include_media": False}
        mock_intent = mocker.patch(
            "lib.stt.transcription_worker.build_intent", return_value="INTENT")

        worker = lib.stt.transcription_worker.TranscriptionWorker()

        mock_intent.assert_called_once_with(matcher, "LLM")
        assert worker._orchestrator._intent == "INTENT"

    def test_init_mini_disabled_by_default(self, mocker):
        """Без intent-конфига оркестратор работает без классификатора."""
        mocker.patch("lib.stt.transcription_worker.get_device_commands_path", return_value="x")
        mocker.patch("lib.stt.transcription_worker.CommandMatcher")
        mocker.patch("lib.stt.transcription_worker.Logger")
        mocker.patch("lib.stt.transcription_worker.TextToSpeech")
        mocker.patch("lib.stt.transcription_worker._provider_manager")
        matcher = lib.stt.transcription_worker.CommandMatcher.return_value
        matcher.get_llm_config.return_value = {}
        matcher.get_intent_config.return_value = {}

        worker = lib.stt.transcription_worker.TranscriptionWorker()

        assert worker._orchestrator._intent is None

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
