"""Тесты Orchestrator: фолбэк в console opencode."""


from lib.orchestrator import Orchestrator


class TestOrchestratorFallback:
    """Нет команды — фоновая отправка в opencode-cli."""

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

    def test_process_text_no_trigger_and_no_command_returns(self, mocker):
        """Строка без триггера и без команды просто печатается."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = False
        orch._matcher.find_command.return_value = (None, [], False)
        orch.process_text("привет мир")
        orch._output.print_text.assert_called_once_with("привет мир")
        orch._matcher.execute_by_id.assert_not_called()

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

    def test_process_text_opencode_answer(self, mocker):
        """Ответ opencode печатается в консоль (print_info) и в лог."""
        opencode = mocker.MagicMock()
        opencode.run.return_value = "Ответ"
        orch = self._make(mocker, opencode=opencode)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_command.return_value = (None, [], False)
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
        orch._matcher.find_command.return_value = (None, [], False)
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
        orch._matcher.find_command.return_value = (None, [], False)
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        orch.process_text("пожалуйста сделай кромку")
        orch._opencode_queue.join()
        for call in orch._output.print_info.call_args_list:
            assert "[Mini]" not in call.args[0]

    def test_process_text_intent_no_detection(self, mocker):
        """Intent вернул None — текст уходит в opencode."""
        opencode = mocker.MagicMock()
        opencode.run.return_value = None
        intent = mocker.MagicMock()
        intent.detect.return_value = None
        orch = self._make(mocker, intent=intent, opencode=opencode)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_command.return_value = (None, [], False)
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
        orch._matcher.find_command.return_value = ("playpause", [], False)
        orch._matcher.missing_requires.return_value = ["media"]
        orch._abort_playback = mocker.MagicMock()
        orch._abort_playback.is_set.return_value = False
        orch.process_text("пожалуйста включи")
        orch._opencode_queue.join()
        orch._matcher.execute_by_id.assert_not_called()
        opencode.run.assert_called_once()
