"""Тесты Orchestrator: инициализация, эхо-затишье, команды level 1."""


import time
from lib.orchestrator import Orchestrator


class TestOrchestratorProcess:
    """Инициализация, гейты обработки, дословные команды."""

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
        orch._matcher.find_command.return_value = ("playpause", [], False)
        orch._matcher.missing_requires.return_value = []
        orch._matcher.execute_by_id.return_value = True
        orch.process_text("пожалуйста пауза")
        orch._matcher.execute_by_id.assert_called_once_with("playpause")
        # print_text вызывается 1 раз: распознанный текст
        orch._output.print_text.assert_called_once_with("пожалуйста пауза")
        orch._output.print_info.assert_any_call(
            "[Command] Распознана команда: playpause")

    def test_process_text_command_with_settings(self, mocker):
        """Команда со настройкой выполняется с ней (execute_by_id)."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_command.return_value = (
            "volumeup", ["немного"], False)
        orch._matcher.missing_requires.return_value = []
        orch._matcher.execute_by_id.return_value = True
        orch.process_text("алиса сделай громче немного")
        orch._matcher.execute_by_id.assert_called_once_with(
            "volumeup", ("немного",))
        orch._output.print_info.assert_any_call(
            "[Command] Распознана команда: volumeup (настройки: немного)")

    def test_process_text_command_blocked_clears_window(self, mocker):
        """Заблокированная команда очищает окно и идёт в intent."""
        intent = mocker.MagicMock()
        intent.detect.return_value = None
        orch = self._make(mocker, intent=intent)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_command.return_value = ("playpause", [], False)
        orch._matcher.missing_requires.return_value = ["media"]
        orch._matcher.status_snapshot.return_value = {"media": False}
        orch.process_text("пожалуйста включи")
        assert len(orch._window) == 0
        text, context = intent.detect.call_args.args
        assert context["blocked"] == [("playpause", ["media"])]

    def test_process_text_wait_holds_for_next_line(self, mocker):
        """wait=True — ничего не выполняем, ждём следующую строку."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_command.return_value = (None, [], True)
        orch._matcher.missing_requires.return_value = []
        orch.process_text("какая же ты тупая алиса")
        orch._matcher.execute_by_id.assert_not_called()
        orch._output.print_text.assert_called_once_with("какая же ты тупая алиса")
        orch._matcher.find_command.assert_called_once_with(["какая же ты тупая алиса"])

    def test_process_text_window_grows_across_lines(self, mocker):
        """Окно строк накапливается: команда находит письмо по ключу."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_command.return_value = (None, [], True)
        orch._matcher.missing_requires.return_value = []
        orch.process_text("какая же ты тупая алиса")
        orch._matcher.find_command.return_value = ("stop", [], False)
        orch._matcher.execute_by_id.return_value = True
        orch.process_text("выключи")
        orch._matcher.execute_by_id.assert_called_once_with("stop")
        calls = [c.args[0] for c in orch._matcher.find_command.call_args_list]
        assert calls == [
            ["какая же ты тупая алиса"],
            ["какая же ты тупая алиса", "выключи"],
        ]

    def test_process_text_command_found_clears_window(self, mocker):
        """После выполнения команды окно строк очищается."""
        orch = self._make(mocker)
        orch._matcher.has_trigger.return_value = True
        orch._matcher.find_command.return_value = ("playpause", [], False)
        orch._matcher.missing_requires.return_value = []
        orch._matcher.execute_by_id.return_value = True
        orch.process_text("пожалуйста пауза")
        assert len(orch._window) == 0
