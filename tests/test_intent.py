"""Тесты LLM-классификатора команд (мини-слоя)."""

from unittest.mock import MagicMock

from lib.intent import IntentClassifier

COMMANDS = {
    "volumeup": ["громче", "сделай громче"],
    "volumedown": ["тише", "сделай тише"],
}


class TestIntentClassifier:
    """Тесты для класса IntentClassifier."""

    def _make(self, probes=None, llm=None, commands=None):
        """Создаёт классификатор с мок-LLM."""
        llm = llm or MagicMock()
        return IntentClassifier(
            commands=commands if commands is not None else dict(COMMANDS),
            llm=llm,
            media_probe=probes,
        ), llm

    def test_detect_returns_command_id(self):
        """LLM вернул id — detect возвращает его."""
        classifier, llm = self._make()
        llm.ask.return_value = "volumeup"
        assert classifier.detect("пожалуйста сделай кромку") == "volumeup"

    def test_detect_strips_quotes_and_case(self):
        """id очищается от кавычек и регистра."""
        classifier, llm = self._make()
        llm.ask.return_value = '"VOLUMEUP"'
        assert classifier.detect("громче") == "volumeup"
        llm.ask.return_value = "«volumedown»"
        assert classifier.detect("тише") == "volumedown"

    def test_detect_none_answer_returns_none(self):
        """LLM ответил NONE — detect возвращает None."""
        classifier, llm = self._make()
        llm.ask.return_value = "NONE"
        assert classifier.detect("пожалуйста сделай поппу") is None

    def test_detect_unknown_id_returns_none(self):
        """LLM вернул несуществующий id — None."""
        classifier, llm = self._make()
        llm.ask.return_value = "playpause"
        assert classifier.detect("что-то") is None

    def test_detect_empty_llm_answer_returns_none(self):
        """LLM вернул пустую строку — None."""
        classifier, llm = self._make()
        llm.ask.return_value = ""
        assert classifier.detect("что-то") is None

    def test_detect_empty_text_no_llm_call(self):
        """Пустой текст — None, LLM не вызывается."""
        classifier, llm = self._make()
        assert classifier.detect("") is None
        assert classifier.detect("   ") is None
        llm.ask.assert_not_called()

    def test_detect_empty_commands_no_llm_call(self):
        """Нет команд — None, LLM не вызывается."""
        classifier, llm = self._make(commands={})
        assert classifier.detect("громче") is None
        llm.ask.assert_not_called()

    def test_prompt_contains_commands_and_media_flag(self):
        """Промпт содержит список команд и флаг медиа."""
        classifier, llm = self._make()
        classifier.detect("пожалуйста сделай кромку")
        prompt = llm.ask.call_args.args[0]
        assert "- volumeup: громче, сделать громче" in prompt or "- volumeup: громче" in prompt
        assert "Сейчас воспроизводится медиа" in prompt
        assert "Запрос пользователя: «пожалуйста сделай кромку»" in prompt

    def test_prompt_uses_media_probe_true(self):
        """При произвольном медиа в промпте «да»."""
        classifier, llm = self._make(probes=lambda: True)
        classifier.detect("громче")
        prompt = llm.ask.call_args.args[0]
        assert "воспроизводится медиа (музыка/видео): да" in prompt

    def test_media_probe_called(self):
        """media_probe вызывается при построении промпта."""
        probe = MagicMock(return_value=False)
        classifier, llm = self._make(probes=probe)
        classifier.detect("громче")
        probe.assert_called_once()

    def test_default_media_probe_is_false(self):
        """Без media_probe в промпте «нет»."""
        classifier, llm = self._make(probes=None)
        classifier.detect("громче")
        prompt = llm.ask.call_args.args[0]
        assert "воспроизводится медиа (музыка/видео): нет" in prompt
