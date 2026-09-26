"""Тесты Orchestrator: озвучка, стоп-слова, воркер opencode."""


import time
from lib.core.orchestrator import Orchestrator


class TestOrchestratorSpeech:
    """TTS-фон, maybe_abort, очередь и остановка."""

    def _make(self, mocker, **kwargs):
        """Создаёт оркестратор с мок-зависимостями."""
        defaults = {
            "matcher": mocker.MagicMock(),
            "output": mocker.MagicMock(),
            "tts": mocker.MagicMock(),
        }
        defaults.update(kwargs)
        orch = Orchestrator(**defaults)
        if "matcher" not in kwargs:
            orch._matcher.find_command.return_value = (None, [], False)
            orch._matcher.missing_requires.return_value = []
            orch._matcher.triggers = ["пожалуйста", "алиса"]
            orch._matcher.status_snapshot.return_value = {}
            orch._matcher.requires_map.return_value = {}
        return orch

    def test_speak_async_plays_in_background(self, mocker):
        """_speak_async запускает озвучку и сбрасывает состояние."""
        orch = self._make(mocker)
        captured = {}

        def _factory(target=None, **kwargs):
            captured["target"] = target
            return mocker.MagicMock()

        mocker.patch("lib.core.orchestrator.threading.Thread", side_effect=_factory)
        orch._speaking = True
        orch._speak_async("Ответ")
        captured["target"]()
        orch._tts.speak_and_play.assert_called_once_with(
            "Ответ", abort_event=orch._abort_playback)
        assert orch.speaking is False
        assert orch.suppress_until > 0

    def test_speak_async_handles_playback_error(self, mocker):
        """Ошибка озвучки печатается, но состояние сбрасывается."""
        orch = self._make(mocker)
        captured = {}

        def _factory(target=None, **kwargs):
            captured["target"] = target
            return mocker.MagicMock()

        mocker.patch("lib.core.orchestrator.threading.Thread", side_effect=_factory)
        orch._tts.speak_and_play.side_effect = RuntimeError("boom")
        orch._speak_async("Ответ")
        captured["target"]()
        orch._output.print_error.assert_called_once_with("Ошибка озвучки: boom")
        assert orch.speaking is False

    def test_maybe_abort_aborts_on_stop_word_token(self, mocker):
        """Стоп-слово внутри фразы прерывает озвучку."""
        orch = self._make(mocker)
        orch._speaking = True
        assert orch.maybe_abort("сделай стоп") is True
        assert orch._abort_playback.is_set()
        orch._output.print_info.assert_called_once_with(
            "[TTS] Озвучка прервана")

    def test_maybe_abort_whole_word_required(self, mocker):
        """Стоп-слово распознаётся только как целое слово."""
        orch = self._make(mocker)
        orch._speaking = True
        assert orch.maybe_abort("стоптанция") is False
        assert not orch._abort_playback.is_set()

    def test_maybe_abort_no_stop_word(self, mocker):
        """Без стоп-слова озвучка не прерывается."""
        orch = self._make(mocker)
        orch._speaking = True
        assert orch.maybe_abort("играет музыка") is False
        assert not orch._abort_playback.is_set()

    def test_maybe_abort_not_speaking(self, mocker):
        """Вне озвучки стоп-слово не считается командой прерывания."""
        orch = self._make(mocker)
        assert orch.maybe_abort("стоп") is False
        assert not orch._abort_playback.is_set()
        orch._output.print_info.assert_not_called()

    def test_maybe_abort_pending_opencode(self, mocker):
        """Стоп-слово во время ожидания ответа opencode отменяет его."""
        orch = self._make(mocker)
        orch._opencode_active = True
        assert orch.maybe_abort("стоп") is True
        assert orch._abort_playback.is_set()
        orch._output.print_info.assert_called_once_with(
            "[OpenCode] Ожидаемый ответ отменён")

    def test_process_text_non_blocking_while_opencode_pending(self, mocker):
        """Пока opencode думает, обычная команда выполняется сразу."""
        opencode = mocker.MagicMock()
        orch = self._make(mocker, opencode=opencode)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_command.return_value = ("playpause", [], False)
        orch._matcher.missing_requires.return_value = []
        orch._matcher.execute_by_id.return_value = True
        orch._opencode_active = True
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        orch.process_text("алиса пауза")
        orch._matcher.execute_by_id.assert_called_once_with("playpause")

    def test_opencode_worker_answers_async(self, mocker):
        """Запрос opencode обрабатывается воркером в фоне, не блокируя loop."""
        opencode = mocker.MagicMock()
        opencode.run.return_value = "Ответ"
        orch = self._make(mocker, opencode=opencode)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_command.return_value = (None, [], False)
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        orch.process_text("пожалуйста расскажи")
        # process_text вернулся сразу, значит _enqueue_opencode не блокировал
        orch._opencode_queue.join()
        opencode.run.assert_called_once_with(
            "пожалуйста расскажи",
            abort_event=orch._abort_playback, raw=False)

    def test_opencode_worker_discards_on_abort(self, mocker):
        """Ответ opencode, пришедший после стоп-слова, не печатается."""
        opencode = mocker.MagicMock()
        opencode.run.return_value = "Запоздавший ответ"
        orch = self._make(mocker, opencode=opencode)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_command.return_value = (None, [], False)
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.side_effect = [False, True]
        orch.process_text("пожалуйста расскажи")
        orch._opencode_queue.join()
        debug = [c.args[0] for c in orch._output.print_debug.call_args_list]
        assert any("[OpenCode] Ответ отменён (стоп)" in call for call in debug)

    def test_stop_drains_pending_opencode(self, mocker):
        """stop() очищает очередь ожидающих opencode-запросов."""
        opencode = mocker.MagicMock()
        orch = self._make(mocker, opencode=opencode)
        mocker.patch.object(orch, "_ensure_opencode_worker")
        orch._enqueue_opencode("один")
        orch._enqueue_opencode("два")
        assert orch._opencode_queue.qsize() == 2
        orch.stop()
        assert orch._opencode_queue.qsize() == 0

    def test_on_speaking_finished(self, mocker):
        """Завершение озвучки сбрасывает флаг и ставит окно эха."""
        orch = self._make(mocker)
        orch._speaking = True
        orch._on_speaking_finished()
        assert orch.speaking is False
        assert orch.suppress_until >= time.monotonic()

    def test_on_speaking_finished_calls_clear_buffer(self, mocker):
        """Колбэк очистки буфера речи вызывается после озвучки."""
        clear = mocker.MagicMock()
        orch = self._make(mocker, clear_speech_buffer=clear)
        orch._on_speaking_finished()
        clear.assert_called_once()

    def test_on_speaking_finished_without_callback(self, mocker):
        """Без колбэка очистки буфера ничего не падает."""
        orch = self._make(mocker)
        orch._on_speaking_finished()
        assert orch.suppress_until > 0

    def test_stop_aborts_playback(self, mocker):
        """stop() прерывает активное воспроизведение."""
        orch = self._make(mocker)
        orch.stop()
        assert orch._abort_playback.is_set()
        assert orch.speaking is False
