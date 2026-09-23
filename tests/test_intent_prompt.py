"""Тесты mini-LLM классификатора: промпт и контекст."""


from unittest.mock import MagicMock
from lib.intent import IntentClassifier

COMMANDS = {
    "volumeup": ["громче", "сделай громче"],
    "volumedown": ["тише", "сделай тише"],
}


class TestIntentPrompt:
    """Промпт, media-probe, контекст блокировок."""

    def _make(self, probes=None, llm=None, commands=None):
        """Создаёт классификатор с мок-LLM."""
        llm = llm or MagicMock()
        return IntentClassifier(
            commands=commands if commands is not None else dict(COMMANDS),
            llm=llm,
            media_probe=probes,
        ), llm

    def test_prompt_contains_commands_and_media_flag(self):
        """Промпт содержит список команд и флаг медиа."""
        classifier, llm = self._make()
        classifier.detect("пожалуйста сделай кромку")
        prompt = llm.classify.call_args.args[0]
        assert "- volumeup: громче, сделать громче" in prompt or "- volumeup: громче" in prompt
        assert "Сейчас воспроизводится медиа" in prompt
        assert "Запрос пользователя: «пожалуйста сделай кромку»" in prompt

    def test_prompt_uses_media_probe_true(self):
        """При произвольном медиа в промпте «да»."""
        classifier, llm = self._make(probes=lambda: True)
        classifier.detect("громче")
        prompt = llm.classify.call_args.args[0]
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
        prompt = llm.classify.call_args.args[0]
        assert "воспроизводится медиа (музыка/видео): нет" in prompt

    def test_context_prompt_has_triggers_statuses_requires(self):
        """Контекстный промпт описывает триггеры, команды и статусы."""
        classifier, llm = self._make(commands={
            "openyoutube": ["открой ютуб"],
            "playpause": ["пауза"],
        })
        llm.ask.return_value = "NONE"
        context = {
            "triggers": ["пожалуйста", "алиса"],
            "statuses": {"vpn": True, "media": False},
            "requires": {"openyoutube": ["vpn"], "playpause": ["media"]},
            "blocked": [("playpause", ["media"])],
        }
        assert classifier.detect("пожалуйста включи и ютюб", context) is None
        prompt = llm.classify.call_args.args[0]
        assert "пожалуйста, алиса" in prompt
        assert "- openyoutube: открой ютуб; требует: vpn" in prompt
        assert "- playpause: пауза; требует: media" in prompt
        assert "vpn=вкл" in prompt
        assert "media=выкл" in prompt
        assert "playpause (нет: media)" in prompt
        assert "Запрос пользователя: «пожалуйста включи и ютюб»" in prompt

    def test_context_detect_returns_command_id(self):
        """LLM вернула id при контексте — detect возвращает его."""
        classifier, llm = self._make(commands={"openyoutube": ["открой ютуб"]})
        llm.classify.return_value = "openyoutube"
        context = {
            "triggers": ["пожалуйста"],
            "statuses": {"vpn": True},
            "requires": {"openyoutube": ["vpn"]},
            "blocked": [],
        }
        assert classifier.detect("пожалуйста включи и ютюб", context) == (
            "openyoutube")

    def test_context_empty_blocked_section(self):
        """Без заблокированных секция пишет «нет»."""
        classifier, llm = self._make()
        llm.ask.return_value = "NONE"
        context = {
            "triggers": ["пожалуйста"],
            "statuses": {},
            "requires": {},
            "blocked": [],
        }
        classifier.detect("пожалуйста что-то", context)
        prompt = llm.classify.call_args.args[0]
        assert "Заблокированы нехваткой статусов: нет" in prompt
