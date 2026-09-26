"""Тесты Orchestrator: mini-LLM intent и алиасы."""


from lib.core.orchestrator import Orchestrator


class TestOrchestratorIntent:
    """Классификатор команд и база алиасов."""

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
            orch._matcher.needs_text.return_value = False
            orch._matcher.triggers = ["пожалуйста", "алиса"]
            orch._matcher.status_snapshot.return_value = {}
            orch._matcher.requires_map.return_value = {}
        return orch

    def _aliases(self, tmp_path, data=None):
        """Настоящий AliasStore во временном файле."""
        import json
        from lib.voice_cmd.aliases import AliasStore
        path = str(tmp_path / "aliases.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data or {"aliases": {}, "pending": {}}, f)
        return AliasStore(path)

    def test_process_text_literal_blocked_goes_to_intent(self, mocker):
        """Дословная, но заблокированная команда — в intent с контекстом."""
        intent = mocker.MagicMock()
        intent.detect.return_value = None
        orch = self._make(mocker, intent=intent)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_command.return_value = ("playpause", [], False)
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
        orch._matcher.find_command.return_value = (None, [], False)
        orch._matcher.execute_by_id.return_value = True
        orch.process_text("пожалуйста включи и ютюб")
        intent.detect.assert_called_once()
        orch._matcher.execute_by_id.assert_called_once_with("openyoutube")

    def test_process_text_intent_executes_detected_command(self, mocker):
        """Intent-слой исполняет распознанную команду и НЕ шлёт в opencode."""
        opencode = mocker.MagicMock()
        intent = mocker.MagicMock()
        intent.detect.return_value = "volumeup"
        orch = self._make(mocker, intent=intent, opencode=opencode)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_command.return_value = (None, [], False)
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
        orch._matcher.find_command.return_value = (None, [], False)
        orch._matcher.execute_by_id.return_value = False
        orch.process_text("пожалуйста сделай кромку")
        orch._matcher.execute_by_id.assert_called_once_with("volumeup")
        calls = [c.args[0] for c in orch._output.print_error.call_args_list]
        assert any("[Mini] Команда «volumeup» не найдена" in call for call in calls)
        orch._opencode_queue.join()
        opencode.run.assert_not_called()

    def test_process_text_intent_blocked_speaks(self, mocker):
        """Intent-команда без статуса: озвучка вместо 'не найдена'."""
        intent = mocker.MagicMock()
        intent.detect.return_value = "openyoutube"
        orch = self._make(mocker, intent=intent)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_command.return_value = (None, [], False)
        orch._matcher.execute_by_id.return_value = False
        orch._matcher.missing_requires.return_value = ["proxy"]
        orch._matcher.need_message.return_value = "Проверь доступность прокси"
        orch._abort_playback = mocker.MagicMock()
        spy = mocker.patch.object(orch, "_speak_async")
        orch.process_text("пожалуйста открой ютуб")
        spy.assert_called_once_with("Проверь доступность прокси")

    def test_process_text_alias_hit_executes(self, mocker, tmp_path):
        """Известное коверканье запускается без LLM."""
        orch = self._make(mocker)
        orch._aliases = self._aliases(tmp_path, {"aliases": {
            "включи и ютюб": {"command": "openyoutube", "hits": 0,
                              "confirmed": True}}, "pending": {}})
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_command.return_value = (None, [], False)
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
        orch._matcher.find_command.return_value = ("openyoutube", [], False)
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
        orch._matcher.find_command.return_value = (None, [], False)
        orch._matcher.core_phrase.return_value = "включи и ютюб"
        orch._matcher.missing_requires.return_value = ["proxy"]
        orch.process_text("алиса включи и ютюб пожалуйста")
        orch._matcher.execute_by_id.assert_not_called()
        text, context = intent.detect.call_args.args
        assert context["blocked"] == [("openyoutube", ["proxy"])]
