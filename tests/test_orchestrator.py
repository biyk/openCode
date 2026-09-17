"""Тесты детерминированного оркестратора обработки текста.

Пайплайн: commands.json (дословно+алиасы) → mini-LLM (intent) →
console opencode (opencode-cli со скиллами). Плюс режим разработки:
«режим разработки» включает pass-through всех фраз в модель напрямую,
«будильник» внутри dev-режима завершает приложение.
"""

import time

from lib.orchestrator import Orchestrator
from lib.orchestrator import DEV_MODE_ENABLE_PHRASE
from lib.orchestrator import DEV_MODE_EXIT_PHRASE


class TestOrchestrator:
    """Тесты для класса Orchestrator."""

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
        assert orch._opencode_queue.empty()
        assert orch._opencode_worker is None
        assert orch._opencode_active is False

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

    def test_process_text_without_trigger(self, mocker):
        """Без триггера текст печатается, opencode не вызывается."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = False
        orch.process_text("привет мир")
        orch._output.print_text.assert_called_once_with("привет мир")

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

    def test_process_text_command_absent_goes_to_opencode(self, mocker):
        """Без дословной команды текст уходит в opencode-cli в фоне."""
        opencode = mocker.MagicMock()
        opencode.run.return_value = "Ответ"
        orch = self._make(mocker, opencode=opencode)
        orch._matcher.has_trigger.return_value = True
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        orch.process_text("пожалуйста сделай кромку")
        orch._opencode_queue.join()
        opencode.run.assert_called_once_with(
            "пожалуйста сделай кромку",
            abort_event=orch._abort_playback, raw=False)
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

    def test_process_text_opencode_answer(self, mocker):
        """Ответ opencode печатается в консоль (print_info) и в лог."""
        opencode = mocker.MagicMock()
        opencode.run.return_value = "Ответ"
        orch = self._make(mocker, opencode=opencode)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        orch.process_text("пожалуйста расскажи")
        orch._opencode_queue.join()
        orch._output.print_info.assert_any_call(
            "... отправка запроса в opencode-cli (фон)")
        # В консоль: старт выполнения + итог ответа
        info_calls = [c.args[0] for c in orch._output.print_info.call_args_list]
        assert any("Выполняю" in c for c in info_calls)
        assert any("[OpenCode] Итог" in c and "Ответ" in c for c in info_calls)
        # В лог: решение + ответ opencode
        assert orch._output.print_debug.call_count == 2
        decision_call = orch._output.print_debug.call_args_list[0][0][0]
        assert "[OpenCode Decision]" in decision_call
        assert "пожалуйста расскажи" in decision_call
        response_call = orch._output.print_debug.call_args_list[1][0][0]
        assert "[OpenCode] Ответ (сводка): Ответ" in response_call
        assert orch.speaking is False
        orch._abort_playback.clear.assert_not_called()

    def test_process_text_opencode_empty(self, mocker):
        """Пустой ответ агента печатается как ошибка."""
        opencode = mocker.MagicMock()
        opencode.run.return_value = None
        orch = self._make(mocker, opencode=opencode)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        orch.process_text("пожалуйста что-то")
        orch._opencode_queue.join()
        error_call = orch._output.print_error.call_args[0][0]
        assert error_call.startswith("[OpenCode] Пустой ответ агента")
        orch._output.print_text.assert_called_once_with("пожалуйста что-то")

    def test_process_text_intent_disabled_no_log(self, mocker):
        """Без intent-слоя текст уходит в opencode, логов [Mini] нет."""
        opencode = mocker.MagicMock()
        opencode.run.return_value = "Ответ"
        orch = self._make(mocker, opencode=opencode)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        orch.process_text("пожалуйста сделай кромку")
        orch._opencode_queue.join()
        for call in orch._output.print_info.call_args_list:
            assert "[Mini]" not in call.args[0]

    def test_process_text_intent_executes_detected_command(self, mocker):
        """Intent-слой исполняет распознанную команду и НЕ шлёт в opencode."""
        opencode = mocker.MagicMock()
        intent = mocker.MagicMock()
        intent.detect.return_value = "volumeup"
        orch = self._make(mocker, intent=intent, opencode=opencode)
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
        orch._opencode_queue.join()
        opencode.run.assert_not_called()

    def test_process_text_intent_execution_fails_no_opencode(self, mocker):
        """Если intent-команда не выполнена — ошибка, opencode не вызывается."""
        opencode = mocker.MagicMock()
        intent = mocker.MagicMock()
        intent.detect.return_value = "volumeup"
        orch = self._make(mocker, intent=intent, opencode=opencode)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._matcher.execute_by_id.return_value = False
        orch.process_text("пожалуйста сделай кромку")
        orch._matcher.execute_by_id.assert_called_once_with("volumeup")
        calls = [c.args[0] for c in orch._output.print_error.call_args_list]
        assert any("[Mini] Команда «volumeup» не найдена" in call for call in calls)
        orch._opencode_queue.join()
        opencode.run.assert_not_called()

    def test_process_text_intent_no_detection(self, mocker):
        """Intent вернул None — текст уходит в opencode."""
        opencode = mocker.MagicMock()
        opencode.run.return_value = None
        intent = mocker.MagicMock()
        intent.detect.return_value = None
        orch = self._make(mocker, intent=intent, opencode=opencode)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        orch.process_text("пожалуйста неизвестный запрос")
        calls = [c.args[0] for c in orch._output.print_info.call_args_list]
        assert not any("[Mini]" in call for call in calls)
        text, context = intent.detect.call_args.args
        assert text == "пожалуйста неизвестный запрос"
        assert set(context) == {"triggers", "statuses", "requires", "blocked"}
        orch._opencode_queue.join()
        opencode.run.assert_called_once()

    def test_process_text_literal_blocked_falls_through_to_opencode(self, mocker):
        """Дословная, но заблокированная, без intent — сигнал идёт в opencode."""
        opencode = mocker.MagicMock()
        opencode.run.return_value = "Ответ"
        orch = self._make(mocker, opencode=opencode)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = "playpause"
        orch._matcher.missing_requires.return_value = ["media"]
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        orch.process_text("пожалуйста включи")
        orch._opencode_queue.join()
        orch._matcher.execute_by_id.assert_not_called()
        opencode.run.assert_called_once()

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
        orch._matcher.find_literal_id.return_value = "playpause"
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
        orch._matcher.find_literal_id.return_value = None
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
        orch._matcher.find_literal_id.return_value = None
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

    def test_dev_mode_disabled_by_default(self, mocker):
        """Режим разработки по умолчанию выключен."""
        orch = self._make(mocker)
        assert orch.dev_mode is False

    def test_dev_mode_enable_phrase_switches_on(self, mocker):
        """«режим разработки» включает dev-режим и подтверждает голосом."""
        orch = self._make(mocker)
        orch._matcher.core_phrase.return_value = DEV_MODE_ENABLE_PHRASE
        spy = mocker.patch.object(orch, "_speak_async")
        orch.process_text("пожалуйста " + DEV_MODE_ENABLE_PHRASE)
        assert orch.dev_mode is True
        spy.assert_called_once()
        assert "Режим разработки" in spy.call_args.args[0]
        orch._matcher.has_trigger.assert_not_called()

    def test_dev_mode_enable_phrase_toggles_off(self, mocker):
        """Повтор фразы выключает dev-режим."""
        orch = self._make(mocker)
        orch._dev_mode = True
        orch._matcher.core_phrase.return_value = DEV_MODE_ENABLE_PHRASE
        orch.process_text(DEV_MODE_ENABLE_PHRASE)
        assert orch.dev_mode is False

    def test_dev_mode_forwards_raw_to_opencode(self, mocker):
        """В dev-режиме любые фразы идут в opencode с raw=True, без матчера."""
        opencode = mocker.MagicMock()
        opencode.run.return_value = "Ответ"
        orch = self._make(mocker, opencode=opencode)
        orch._dev_mode = True
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = "playpause"
        orch._matcher.missing_requires.return_value = []
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        orch.process_text("проверь последние логи и исправь ошибку")
        orch._opencode_queue.join()
        orch._matcher.execute_by_id.assert_not_called()
        opencode.run.assert_called_once_with(
            "проверь последние логи и исправь ошибку",
            abort_event=orch._abort_playback, raw=True)

    def test_dev_mode_stop_alarm_exits(self, mocker):
        """«будильник» в dev-режиме вызывает on_exit."""
        exited = {}
        on_exit = mocker.MagicMock(side_effect=lambda: exited.update(done=True))
        orch = self._make(mocker, on_exit=on_exit)
        orch._dev_mode = True
        orch._matcher.core_phrase.return_value = DEV_MODE_EXIT_PHRASE
        orch.process_text(DEV_MODE_EXIT_PHRASE)
        assert exited.get("done") is True
        orch._matcher.has_trigger.assert_not_called()

    def test_dev_mode_stop_alarm_ignored_when_off(self, mocker):
        """Вне dev-режима «будильник» идёт обычным путём, без on_exit."""
        on_exit = mocker.MagicMock()
        orch = self._make(mocker, on_exit=on_exit)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_literal_id.return_value = None
        orch._matcher.core_phrase.return_value = DEV_MODE_EXIT_PHRASE
        orch.process_text(DEV_MODE_EXIT_PHRASE)
        on_exit.assert_not_called()
        assert orch.dev_mode is False
