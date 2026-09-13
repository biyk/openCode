"""Тесты детерминированного оркестратора обработки текста."""

import time

from lib.orchestrator import Orchestrator


class TestOrchestrator:
    """Тесты для класса Orchestrator."""

    def _make(self, mocker, **kwargs):
        """Создаёт оркестратор с мок-зависимостями."""
        defaults = {
            "matcher": mocker.MagicMock(),
            "output": mocker.MagicMock(),
            "llm": mocker.MagicMock(),
            "tts": mocker.MagicMock(),
        }
        defaults.update(kwargs)
        orch = Orchestrator(**defaults)
        if "matcher" not in kwargs:
            orch._matcher.find_literal_id.return_value = None
            orch._matcher.missing_requires.return_value = []
            orch._matcher.triggers = ["пожалуйста", "алиса"]
            orch._matcher.status_snapshot.return_value = {}
            orch._matcher.requires_map.return_value = {}
        return orch

    def test_defaults(self, mocker):
        """Стоп-слова и окно эха задаются по умолчанию."""
        orch = self._make(mocker)
        assert "стоп" in orch._stop_words
        assert "останови" in orch._stop_words
        assert orch._suppress_after == 0.5
        assert orch.speaking is False
        assert orch.suppress_until == 0.0
        assert orch.abort_playback is not None

    def test_custom_stop_words_and_suppress(self, mocker):
        """Кастомные стоп-слова и окно эха переопределяются."""
        orch = self._make(
            mocker, stop_words=frozenset(("хватит",)),
            suppress_after=2.0)
        assert orch._stop_words == frozenset(("хватит",))
        assert orch._suppress_after == 2.0

    def test_process_text_ignored_within_suppress_window(self, mocker):
        """В окне эхо-затишья текст не обрабатывается."""
        orch = self._make(mocker)
        orch._suppress_until = time.monotonic() + 60
        orch.process_text("пожалуйста что-то")
        orch._matcher.has_trigger.assert_not_called()
        orch._output.print_text.assert_not_called()
        orch._llm.ask.assert_not_called()

    def test_process_text_ignored_in_past_suppress_window(self, mocker):
        """Затишье в прошлом событии block — но окно истекло, обработка идёт."""
        orch = self._make(mocker)
        orch._suppress_until = 10.0
        mocker.patch("lib.orchestrator.time.monotonic", return_value=11.0)
        orch._matcher.has_trigger.return_value = False
        orch.process_text("привет")
        orch._output.print_text.assert_called_once_with("привет")

    def test_process_text_stop_word_aborts_playback(self, mocker):
        """Стоп-слово во время озвучки прерывает её."""
        orch = self._make(mocker)
        orch._speaking = True
        mocker.patch("lib.orchestrator.time.monotonic", return_value=1.0)
        orch._suppress_until = 0.5
        orch.process_text("стоп")
        assert orch._abort_playback.is_set()
        orch._output.print_info.assert_called_once_with("[TTS] Озвучка прервана")
        orch._matcher.has_trigger.assert_not_called()

    def test_process_text_ignores_non_stop_word_while_speaking(self, mocker):
        """Во время озвучки игнорируются все слова кроме стоп-слов."""
        orch = self._make(mocker)
        orch._speaking = True
        orch._suppress_until = 0.0
        orch.process_text("пожалуйста что-то")
        orch._matcher.has_trigger.assert_not_called()
        assert not orch._abort_playback.is_set()
        orch._output.print_text.assert_not_called()
        orch._llm.ask.assert_not_called()

    def test_process_text_without_trigger(self, mocker):
        """Без триггера текст печатается, LLM не вызывается."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = False
        orch.process_text("привет мир")
        orch._output.print_text.assert_called_once_with("привет мир")
        orch._llm.ask.assert_not_called()

    def test_process_text_command_found(self, mocker):
        """Дословная команда с триггером выполняется (id в print_info)."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = "playpause"
        orch._matcher.missing_requires.return_value = []
        orch._matcher.execute_by_id.return_value = True
        orch.process_text("пожалуйста пауза")
        orch._matcher.execute_by_id.assert_called_once_with("playpause")
        # print_text вызывается 1 раз: распознанный текст
        orch._output.print_text.assert_called_once_with("пожалуйста пауза")
        orch._output.print_info.assert_any_call(
            "[Command] Распознана команда: playpause")
        orch._llm.ask.assert_not_called()

    def test_process_text_command_absent(self, mocker):
        """Без дословной команды текст уходит дальше (intent/LLM)."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._llm.ask.return_value = "Ответ"
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        spy = mocker.patch.object(orch, "_speak_async")
        orch.process_text("пожалуйста сделай кромку")
        spy.assert_called_once_with("Ответ")
        orch._matcher.execute_by_id.assert_not_called()

    def test_process_text_literal_blocked_goes_to_intent(self, mocker):
        """Дословная, но заблокированная команда — в intent с контекстом."""
        intent = mocker.MagicMock()
        intent.detect.return_value = None
        orch = self._make(mocker, intent=intent)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = "playpause"
        orch._matcher.missing_requires.return_value = ["media"]
        orch._matcher.status_snapshot.return_value = {"media": False}
        orch._llm.ask.return_value = None
        orch.process_text("пожалуйста включи")
        orch._matcher.execute_by_id.assert_not_called()
        text, context = intent.detect.call_args.args
        assert text == "пожалуйста включи"
        assert context["blocked"] == [("playpause", ["media"])]
        assert context["triggers"] == ["пожалуйста", "алиса"]
        assert context["statuses"] == {"media": False}

    def test_process_text_garbled_goes_to_intent(self, mocker):
        """Исковерканное Vosk («ютюб») — в intent, не в подстроку."""
        intent = mocker.MagicMock()
        intent.detect.return_value = "openyoutube"
        orch = self._make(mocker, intent=intent)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._matcher.execute_by_id.return_value = True
        orch.process_text("пожалуйста включи и ютюб")
        intent.detect.assert_called_once()
        orch._matcher.execute_by_id.assert_called_once_with("openyoutube")
        orch._llm.ask.assert_not_called()

    def test_process_text_llm_answer(self, mocker):
        """Без команды ответ LLM озвучивается в фоне."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._llm.ask.return_value = "Ответ"
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        spy = mocker.patch.object(orch, "_speak_async")
        orch.process_text("пожалуйста расскажи")
        orch._output.print_info.assert_called_once_with(
            "... отправка запроса LLM")
        # print_debug вызывается 2 раза: решение + ответ LLM
        assert orch._output.print_debug.call_count == 2
        decision_call = orch._output.print_debug.call_args_list[0][0][0]
        assert "[LLM Decision]" in decision_call
        assert "пожалуйста расскажи" in decision_call
        response_call = orch._output.print_debug.call_args_list[1][0][0]
        assert "[LLM] Ответ: Ответ" in response_call
        assert orch.speaking is True
        assert not orch._abort_playback.is_set()
        orch._abort_playback.clear.assert_called_once()
        spy.assert_called_once_with("Ответ")

    def test_process_text_llm_error(self, mocker):
        """Ошибка LLM печатается как текст."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._llm.ask.return_value = None
        orch.process_text("пожалуйста что-то")
        orch._output.print_error.assert_called_once_with("[LLM] Ошибка ответа")
        # print_text вызывается 2 раза: распознанный текст + текст ошибки
        assert orch._output.print_text.call_count == 2
        orch._output.print_text.assert_any_call("пожалуйста что-то")

    def test_process_text_intent_disabled_no_log(self, mocker):
        """Без intent-слоя текст уходит в LLM, логов [Mini] нет."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._llm.ask.return_value = "Ответ"
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        spy = mocker.patch.object(orch, "_speak_async")
        orch.process_text("пожалуйста сделай кромку")
        spy.assert_called_once_with("Ответ")
        for call in orch._output.print_info.call_args_list:
            assert "[Mini]" not in call.args[0]

    def test_process_text_intent_executes_detected_command(self, mocker):
        """Intent-слой исполняет распознанную команду и НЕ шлёт в LLM."""
        intent = mocker.MagicMock()
        intent.detect.return_value = "volumeup"
        orch = self._make(mocker, intent=intent)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._matcher.execute_by_id.return_value = True
        orch.process_text("пожалуйста сделай кромку")
        text, context = intent.detect.call_args.args
        assert text == "пожалуйста сделай кромку"
        assert context["blocked"] == []
        orch._matcher.execute_by_id.assert_called_once_with("volumeup")
        # print_text вызывается 2 раза: распознанный текст + команда
        assert orch._output.print_text.call_count == 2
        orch._output.print_text.assert_any_call("пожалуйста сделай кромку")
        orch._output.print_text.assert_any_call("volumeup")
        orch._llm.ask.assert_not_called()

    def test_process_text_intent_execution_fails_no_llm(self, mocker):
        """Если intent-команда не выполнена — ошибка, LLM не вызывается."""
        intent = mocker.MagicMock()
        intent.detect.return_value = "volumeup"
        orch = self._make(mocker, intent=intent)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._matcher.execute_by_id.return_value = False
        orch.process_text("пожалуйста сделай кромку")
        orch._matcher.execute_by_id.assert_called_once_with("volumeup")
        calls = [c.args[0] for c in orch._output.print_error.call_args_list]
        assert any("[Mini] Команда «volumeup» не найдена" in call for call in calls)
        orch._llm.ask.assert_not_called()

    def test_process_text_intent_no_detection(self, mocker):
        """Intent вернул None — текст уходит в обычный запрос LLM."""
        intent = mocker.MagicMock()
        intent.detect.return_value = None
        orch = self._make(mocker, intent=intent)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._llm.ask.return_value = None
        orch.process_text("пожалуйста неизвестный запрос")
        calls = [c.args[0] for c in orch._output.print_info.call_args_list]
        assert not any("[Mini]" in call for call in calls)
        text, context = intent.detect.call_args.args
        assert text == "пожалуйста неизвестный запрос"
        assert set(context) == {"triggers", "statuses", "requires", "blocked"}

    def test_process_text_literal_blocked_falls_through_to_llm(self, mocker):
        """Дословная, но заблокированная, без intent — сигнал идёт в LLM."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = "playpause"
        orch._matcher.missing_requires.return_value = ["media"]
        orch._llm.ask.return_value = "Ответ"
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        spy = mocker.patch.object(orch, "_speak_async")
        orch.process_text("пожалуйста включи")
        orch._matcher.execute_by_id.assert_not_called()
        spy.assert_called_once_with("Ответ")

    def test_process_text_intent_blocked_speaks(self, mocker):
        """Intent-команда без статуса: озвучка вместо 'не найдена'."""
        intent = mocker.MagicMock()
        intent.detect.return_value = "openyoutube"
        orch = self._make(mocker, intent=intent)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._matcher.execute_by_id.return_value = False
        orch._matcher.missing_requires.return_value = ["vpn"]
        orch._matcher.need_message.return_value = "Включи VPN вручную"
        orch._abort_playback = mocker.MagicMock()
        spy = mocker.patch.object(orch, "_speak_async")
        orch.process_text("пожалуйста открой ютуб")
        spy.assert_called_once_with("Включи VPN вручную")
        orch._llm.ask.assert_not_called()

    def test_speak_async_plays_in_background(self, mocker):
        """_speak_async запускает озвучку и сбрасывает состояние."""
        orch = self._make(mocker)
        captured = {}

        def _factory(target=None, **kwargs):
            captured["target"] = target
            return mocker.MagicMock()

        mocker.patch("lib.orchestrator.threading.Thread", side_effect=_factory)
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

        mocker.patch("lib.orchestrator.threading.Thread", side_effect=_factory)
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
