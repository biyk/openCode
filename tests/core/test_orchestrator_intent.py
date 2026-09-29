"""Тесты Orchestrator: mini-LLM intent."""


from lib.core.orchestrator import Orchestrator


class TestOrchestratorIntent:
    """Классификатор команд mini-LLM."""

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
            orch._matcher.find_command.return_value = (None, [])
            orch._matcher.missing_requires.return_value = []
            orch._matcher.needs_text.return_value = False
            orch._matcher.triggers = ["пожалуйста", "алиса"]
            orch._matcher.status_snapshot.return_value = {}
            orch._matcher.requires_map.return_value = {}
        return orch

    def test_process_text_literal_blocked_goes_to_intent(self, mocker):
        """Дословная, но заблокированная команда — в intent с контекстом."""
        intent = mocker.MagicMock()
        intent.detect.return_value = None
        orch = self._make(mocker, intent=intent)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_command.return_value = ("playpause", [])
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
        orch._matcher.find_command.return_value = (None, [])
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
        orch._matcher.find_command.return_value = (None, [])
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
        orch._matcher.find_command.return_value = (None, [])
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
        orch._matcher.find_command.return_value = (None, [])
        orch._matcher.execute_by_id.return_value = False
        orch._matcher.missing_requires.return_value = ["proxy"]
        orch._matcher.need_message.return_value = "Проверь доступность прокси"
        orch._abort_playback = mocker.MagicMock()
        spy = mocker.patch.object(orch, "_speak_async")
        orch.process_text("пожалуйста открой ютуб")
        spy.assert_called_once_with("Проверь доступность прокси")
