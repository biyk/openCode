"""Тесты Orchestrator: голосовое обучение «запомни»/«забудь»."""


from lib.orchestrator import Orchestrator


class TestOrchestratorMemory:
    """Алиасы голосом и pending-кандидаты."""

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

    def _aliases(self, tmp_path, data=None):
        """Настоящий AliasStore во временном файле."""
        import json
        from lib.aliases import AliasStore
        path = str(tmp_path / "aliases.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data or {"aliases": {}, "pending": {}}, f)
        return AliasStore(path)

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
        orch._matcher.find_command.return_value = (None, [], False)
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
