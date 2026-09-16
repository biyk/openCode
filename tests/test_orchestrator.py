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
        assert orch._llm_queue.empty()
        assert orch._llm_worker is None
        assert orch._llm_active is False

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
        orch._llm_queue.join()
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
        orch._llm_queue.join()
        orch._output.print_info.assert_called_once_with(
            "... отправка запроса LLM (фон)")
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
        orch._llm_queue.join()
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
        orch._llm_queue.join()
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
        orch._llm_queue.join()
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

    def _aliases(self, tmp_path, data=None):
        """Настоящий AliasStore во временном файле."""
        import json
        from lib.aliases import AliasStore
        path = str(tmp_path / "aliases.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data or {"aliases": {}, "pending": {}}, f)
        return AliasStore(path)

    def test_process_text_alias_hit_executes(self, mocker, tmp_path):
        """Известное коверканье запускается без LLM."""
        orch = self._make(mocker)
        orch._aliases = self._aliases(tmp_path, {"aliases": {
            "включи и ютюб": {"command": "openyoutube", "hits": 0,
                              "confirmed": True}}, "pending": {}})
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._matcher.core_phrase.return_value = "включи и ютюб"
        orch._matcher.missing_requires.return_value = []
        orch._matcher.execute_by_id.return_value = True
        orch.process_text("алиса включи и ютюб пожалуйста")
        orch._matcher.execute_by_id.assert_called_once_with("openyoutube")
        orch._output.print_info.assert_any_call(
            "[Alias] Распознана команда: openyoutube")
        orch._llm.ask.assert_not_called()

    def test_process_text_literal_beats_alias(self, mocker, tmp_path):
        """Дословный шаблон важнее алиаса на тот же текст."""
        orch = self._make(mocker)
        orch._aliases = self._aliases(tmp_path)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = "openyoutube"
        orch._matcher.missing_requires.return_value = []
        orch._matcher.execute_by_id.return_value = True
        orch._matcher.core_phrase.return_value = "открой ютуб"
        orch.process_text("алиса открой ютуб пожалуйста")
        orch._matcher.execute_by_id.assert_called_once_with("openyoutube")
        orch._output.print_info.assert_any_call(
            "[Command] Распознана команда: openyoutube")

    def test_process_text_alias_blocked_goes_to_intent(self, mocker, tmp_path):
        """Заблокированный алиас — в intent с контекстом."""
        intent = mocker.MagicMock()
        intent.detect.return_value = None
        orch = self._make(mocker, intent=intent)
        orch._aliases = self._aliases(tmp_path, {"aliases": {
            "включи и ютюб": {"command": "openyoutube", "hits": 0,
                              "confirmed": True}}, "pending": {}})
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._matcher.core_phrase.return_value = "включи и ютюб"
        orch._matcher.missing_requires.return_value = ["vpn"]
        orch._llm.ask.return_value = None
        orch.process_text("алиса включи и ютюб пожалуйста")
        orch._matcher.execute_by_id.assert_not_called()
        text, context = intent.detect.call_args.args
        assert context["blocked"] == [("openyoutube", ["vpn"])]

    def test_process_text_remember_direct(self, mocker, tmp_path):
        """«запомни X это Y» сохраняет алиас и подтверждает голосом."""
        orch = self._make(mocker)
        orch._aliases = self._aliases(tmp_path)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.core_phrase.return_value = (
            "запомни включи и ютюб это openyoutube")
        orch._matcher.match_config.return_value = {
            "openyoutube": ["открой ютуб"]}
        orch._matcher.sequences.return_value = {}
        spy = mocker.patch.object(orch, "_speak_async")
        orch.process_text("алиса запомни включи и ютюб это openyoutube")
        assert orch._aliases.resolve("включи и ютюб") == "openyoutube"
        spy.assert_called_once()
        assert "Запомнила" in spy.call_args.args[0]
        orch._matcher.execute_by_id.assert_not_called()
        orch._llm.ask.assert_not_called()

    def test_process_text_remember_unknown_id(self, mocker, tmp_path):
        """«запомни» с неизвестной командой — отказ голосом."""
        orch = self._make(mocker)
        orch._aliases = self._aliases(tmp_path)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.core_phrase.return_value = "запомни громче это нетакой"
        orch._matcher.match_config.return_value = {"volumeup": ["громче"]}
        orch._matcher.sequences.return_value = {}
        spy = mocker.patch.object(orch, "_speak_async")
        orch.process_text("алиса запомни громче это нетакой")
        assert orch._aliases.resolve("громче") is None
        assert "Не знаю команду" in spy.call_args.args[0]

    def test_process_text_remember_nothing(self, mocker, tmp_path):
        """«запомни» без истории — «Нечего запоминать»."""
        orch = self._make(mocker)
        orch._aliases = self._aliases(tmp_path)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.core_phrase.return_value = "запомни"
        spy = mocker.patch.object(orch, "_speak_async")
        orch.process_text("алиса запомни пожалуйста")
        assert "Нечего запоминать" in spy.call_args.args[0]

    def test_process_text_forget(self, mocker, tmp_path):
        """«забудь X» удаляет алиас."""
        orch = self._make(mocker)
        orch._aliases = self._aliases(tmp_path, {"aliases": {
            "включи и ютюб": {"command": "openyoutube", "hits": 1,
                              "confirmed": True}}, "pending": {}})
        orch._matcher.has_trigger.return_value = True
        orch._matcher.core_phrase.return_value = "забудь включи и ютюб"
        spy = mocker.patch.object(orch, "_speak_async")
        orch.process_text("алиса забудь включи и ютюб пожалуйста")
        assert orch._aliases.resolve("включи и ютюб") is None
        assert "Забыла" in spy.call_args.args[0]

    def test_process_text_pending_auto_added(self, mocker, tmp_path):
        """Успешный недословный intent-резолв попадает в pending."""
        intent = mocker.MagicMock()
        intent.detect.return_value = "openyoutube"
        orch = self._make(mocker, intent=intent)
        orch._aliases = self._aliases(tmp_path)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._matcher.core_phrase.return_value = "включи и ютюб"
        orch._matcher.execute_by_id.return_value = True
        orch.process_text("алиса включи и ютюб пожалуйста")
        assert "включи и ютюб" in orch._aliases.pending_list()

    def test_process_text_remember_confirms_pending(self, mocker, tmp_path):
        """«запомни» подтверждает pending-запись."""
        orch = self._make(mocker)
        orch._aliases = self._aliases(tmp_path, {"aliases": {}, "pending": {
            "паузы": {"command": "playpause", "hits": 0,
                      "confirmed": False}}})
        orch._last_resolution = ("паузы", "playpause")
        orch._matcher.has_trigger.return_value = True
        orch._matcher.core_phrase.return_value = "запомни"
        spy = mocker.patch.object(orch, "_speak_async")
        orch.process_text("алиса запомни пожалуйста")
        assert orch._aliases.resolve("паузы") == "playpause"
        assert "Запомнила" in spy.call_args.args[0]

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

    def test_maybe_abort_pending_llm(self, mocker):
        """Стоп-слово во время ожидания ответа LLM отменяет его."""
        orch = self._make(mocker)
        orch._llm_active = True
        assert orch.maybe_abort("стоп") is True
        assert orch._abort_playback.is_set()
        orch._output.print_info.assert_called_once_with(
            "[LLM] Ожидаемый ответ отменён")

    def test_process_text_non_blocking_while_llm_pending(self, mocker):
        """Пока LLM думает, обычная команда выполняется сразу."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = "playpause"
        orch._matcher.missing_requires.return_value = []
        orch._matcher.execute_by_id.return_value = True
        orch._llm_active = True
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        orch.process_text("алиса пауза")
        orch._matcher.execute_by_id.assert_called_once_with("playpause")

    def test_llm_worker_answers_async(self, mocker):
        """Запрос LLM обрабатывается воркером в фоне, не блокируя loop."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._llm.ask.return_value = "Ответ"
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        spy = mocker.patch.object(orch, "_speak_async")
        orch.process_text("пожалуйста расскажи")
        # process_text вернулся сразу, значит _enqueue_llm не блокировал
        orch._llm_queue.join()
        spy.assert_called_once_with("Ответ")
        orch._llm.ask.assert_called_once_with("пожалуйста расскажи")

    def test_llm_worker_discards_on_abort(self, mocker):
        """Ответ LLM, пришедший после стоп-слова, не озвучивается."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._llm.ask.return_value = "Запоздавший ответ"
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.side_effect = [False, True]
        spy = mocker.patch.object(orch, "_speak_async")
        orch.process_text("пожалуйста расскажи")
        orch._llm_queue.join()
        spy.assert_not_called()
        orch._output.print_debug.assert_any_call("[LLM] Ответ отменён (стоп)")

    def test_stop_drains_pending_llm(self, mocker):
        """stop() очищает очередь ожидающих LLM-запросов."""
        orch = self._make(mocker)
        mocker.patch.object(orch, "_ensure_llm_worker")
        orch._enqueue_llm("один")
        orch._enqueue_llm("два")
        assert orch._llm_queue.qsize() == 2
        orch.stop()
        assert orch._llm_queue.qsize() == 0

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

    def test_process_text_reminder_succeeds(self, mocker, tmp_path):
        """Напоминание создаёт задачу в Tasks и озвучивается."""
        reminder = mocker.MagicMock()
        reminder.is_reminder.return_value = True
        orch = self._make(mocker, reminders=reminder)
        spec = mocker.MagicMock()
        spec.text = "постирать"
        spec.when.strftime.return_value = "15.09 13:00"
        reminder.create.return_value = spec
        reminder.add_event.return_value = "event-abc"
        orch._abort_playback = mocker.MagicMock()
        # Не запускать реальный поток TTS
        spoken = []
        orch._speak_async = lambda ans: (spoken.append(ans),
                                         setattr(orch, '_speaking', True))
        orch.process_text("алиса напомни мне через 3 часа постирать")
        reminder.is_reminder.assert_called_once()
        reminder.create.assert_called_once()
        reminder.add_event.assert_called_once_with(spec)
        assert orch._speaking is True
        assert len(spoken) == 1
        assert "постирать" in spoken[0]

    def test_process_text_reminder_no_time(self, mocker):
        """Пустое напоминание — голосовое сообщение об ошибке."""
        reminder = mocker.MagicMock()
        reminder.is_reminder.return_value = True
        reminder.create.return_value = None
        orch = self._make(mocker, reminders=reminder)
        orch._abort_playback = mocker.MagicMock()
        spoken = []
        orch._speak_async = lambda ans: (spoken.append(ans),
                                         setattr(orch, '_speaking', True))
        orch.process_text("алиса напомни постирать")
        reminder.create.assert_called_once()
        reminder.add_event.assert_not_called()
        assert orch._speaking is True
        assert any("напомнить" in s.lower()
                   for s in spoken)

    def test_process_text_reminder_google_failure(self, mocker):
        """Ошибка Google API → голосовое сообщение и return."""
        reminder = mocker.MagicMock()
        reminder.is_reminder.return_value = True
        spec = mocker.MagicMock()
        spec.when.strftime.return_value = "15.09 13:00"
        spec.text = "тест"
        reminder.create.return_value = spec
        reminder.add_event.return_value = None
        orch = self._make(mocker, reminders=reminder)
        orch._abort_playback = mocker.MagicMock()
        spoken = []
        orch._speak_async = lambda ans: (spoken.append(ans),
                                         setattr(orch, '_speaking', True))
        orch.process_text("алиса напомни мне через 3 часа тест")
        reminder.add_event.assert_called_once()
        assert orch._speaking is True
        assert any("ошибк" in s.lower() or "авторизац" in s.lower()
                   for s in spoken)

    def test_process_text_reminder_cancels_not_literal(self, mocker):
        """Напоминание не проходит literal-матчинг."""
        reminder = mocker.MagicMock()
        reminder.is_reminder.return_value = True
        reminder.create.return_value = None
        orch = self._make(mocker, reminders=reminder)
        orch._abort_playback = mocker.MagicMock()
        orch._speak_async = lambda ans: setattr(orch, '_speaking', True)
        orch.process_text("алиса напомни мне через 3 часа")
        reminder.create.assert_called_once()
        orch._matcher.find_literal_id.assert_not_called()

    def test_process_text_plans_speaks_current_task(self, mocker):
        """Запрос планов озвучивает актуальную задачу."""
        from datetime import datetime
        plans = mocker.MagicMock()
        plans.is_plans_query.return_value = True
        plans.auth_ready.return_value = True
        plans.current_task.return_value = {
            "id": "e1", "summary": "созвон",
            "start": datetime(2026, 9, 15, 13, 0),
            "end": datetime(2026, 9, 15, 13, 30),
        }
        orch = self._make(mocker, plans=plans)
        orch._abort_playback = mocker.MagicMock()
        spoken = []
        orch._speak_async = lambda ans: (spoken.append(ans),
                                         setattr(orch, '_speaking', True))
        orch.process_text("алиса что у меня сейчас по планам")
        plans.current_task.assert_called_once()
        assert orch._speaking is True
        assert len(spoken) == 1
        assert "созвон" in spoken[0]
        assert "13:00" in spoken[0]
        orch._matcher.find_literal_id.assert_not_called()
        orch._llm.ask.assert_not_called()

    def test_process_text_plans_empty_calendar(self, mocker):
        """Пустой календарь — «По планам сейчас ничего нет»."""
        plans = mocker.MagicMock()
        plans.is_plans_query.return_value = True
        plans.auth_ready.return_value = True
        plans.current_task.return_value = None
        orch = self._make(mocker, plans=plans)
        orch._abort_playback = mocker.MagicMock()
        spoken = []
        orch._speak_async = lambda ans: (spoken.append(ans),
                                         setattr(orch, '_speaking', True))
        orch.process_text("алиса что у меня сейчас по планам")
        assert any("ничего нет" in s.lower() for s in spoken)

    def test_process_text_plans_not_authorized(self, mocker):
        """Без авторизации — просьба авторизоваться."""
        plans = mocker.MagicMock()
        plans.is_plans_query.return_value = True
        plans.auth_ready.return_value = False
        orch = self._make(mocker, plans=plans)
        orch._abort_playback = mocker.MagicMock()
        spoken = []
        orch._speak_async = lambda ans: (spoken.append(ans),
                                         setattr(orch, '_speaking', True))
        orch.process_text("алиса что у меня сейчас по планам")
        plans.current_task.assert_not_called()
        assert any("авторизац" in s.lower() for s in spoken)

    def test_process_text_plans_not_query_falls_through(self, mocker):
        """Не-запрос планов не перехватывается."""
        plans = mocker.MagicMock()
        plans.is_plans_query.return_value = False
        orch = self._make(mocker, plans=plans)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = "playpause"
        orch._matcher.missing_requires.return_value = []
        orch._matcher.execute_by_id.return_value = True
        orch.process_text("алиса пауза")
        plans.current_task.assert_not_called()
        orch._matcher.execute_by_id.assert_called_once_with("playpause")

    def test_reminder_is_optional(self, mocker):
        """Нет reminders → обход без ошибок."""
        orch = self._make(mocker, reminders=None)
        orch._abort_playback = mocker.MagicMock()
        orch.process_text("алиса пауза")
        orch._matcher.find_literal_id.assert_called_once_with("алиса пауза")
