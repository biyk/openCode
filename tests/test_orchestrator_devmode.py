"""Тесты Orchestrator: режим разработки."""


from lib.orchestrator import Orchestrator
from lib.orchestrator_speech import DEV_MODE_ENABLE_PHRASE
from lib.orchestrator_speech import DEV_MODE_EXIT_PHRASE


class TestOrchestratorDevmode:
    """Включение, pass-through фраз, выход по «будильнику»."""

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
        orch._matcher.find_command.return_value = ("playpause", [], False)
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
        orch._matcher.find_command.return_value = (None, [], False)
        orch._matcher.core_phrase.return_value = DEV_MODE_EXIT_PHRASE
        orch.process_text(DEV_MODE_EXIT_PHRASE)
        on_exit.assert_not_called()
        assert orch.dev_mode is False
