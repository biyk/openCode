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
        llm.classify.return_value = "volumeup"
        assert classifier.detect("пожалуйста сделай кромку") == "volumeup"

    def test_detect_uses_classify_not_ask(self):
        """При наличии classify() обычный ask() не вызывается."""
        classifier, llm = self._make()
        llm.classify.return_value = "volumeup"
        assert classifier.detect("громче") == "volumeup"
        llm.ask.assert_not_called()
        assert llm.classify.call_count == 1

    def test_detect_falls_back_to_ask(self):
        """Без classify() — старый путь через ask()."""
        from types import SimpleNamespace
        ask_mock = MagicMock(return_value="volumeup")
        stub = SimpleNamespace(ask=ask_mock)
        classifier, _ = self._make(llm=stub)
        assert classifier.detect("громче") == "volumeup"
        ask_mock.assert_called_once()

    def test_detect_strips_quotes_and_case(self):
        """id очищается от кавычек и регистра."""
        classifier, llm = self._make()
        llm.classify.return_value = '"VOLUMEUP"'
        assert classifier.detect("громче") == "volumeup"
        llm.classify.return_value = "«volumedown»"
        assert classifier.detect("тише") == "volumedown"

    def test_detect_none_answer_returns_none(self):
        """LLM ответил NONE — detect возвращает None."""
        classifier, llm = self._make()
        llm.classify.return_value = "NONE"
        assert classifier.detect("пожалуйста сделай поппу") is None

    def test_detect_unknown_id_returns_none(self):
        """LLM вернул несуществующий id — None."""
        classifier, llm = self._make()
        llm.classify.return_value = "playpause"
        assert classifier.detect("что-то") is None

    def test_detect_empty_llm_answer_returns_none(self):
        """LLM вернул пустую строку — None."""
        classifier, llm = self._make()
        llm.classify.return_value = ""
        assert classifier.detect("что-то") is None

    def test_detect_extracts_id_with_junk_after(self):
        """id + объяснения после — извлекается id (кейс omni из лога)."""
        classifier, llm = self._make(commands={"playpause": ["пауза"]})
        llm.classify.return_value = (
            "playpause\n\nПравила работы:\n1. Разбить текст на N-граммы.")
        assert classifier.detect("паузы пожалуйста") == "playpause"

    def test_detect_extracts_id_first_word(self):
        """id первое слово с точкой — извлекается."""
        classifier, llm = self._make()
        llm.classify.return_value = "Volumeup."
        assert classifier.detect("громче") == "volumeup"

    def test_detect_none_with_dot_returns_none(self):
        """'NONE.' — это отказ, не команда."""
        classifier, llm = self._make()
        llm.classify.return_value = "NONE."
        assert classifier.detect("что-то") is None

    def test_detect_finds_id_inside_sentence(self):
        """id внутри предложения находится по целому слову."""
        classifier, llm = self._make(commands={"openyoutube": ["открой ютуб"]})
        llm.classify.return_value = "Думаю, это openyoutube."
        assert classifier.detect("включи ютуб") == "openyoutube"

    def test_detect_no_substring_false_positive(self):
        """news внутри youtube_news — не совпадение."""
        classifier, llm = self._make(commands={
            "youtube_news": ["новости ютуб"], "news": ["новости"]})
        llm.classify.return_value = "Смотри youtube_news."
        assert classifier.detect("новости") == "youtube_news"

    def test_detect_non_string_answer_returns_none(self):
        """Нестроковый ответ — None без падения."""
        classifier, llm = self._make()
        llm.classify.return_value = 42
        assert classifier.detect("громче") is None

    def test_detect_empty_text_no_llm_call(self):
        """Пустой текст — None, LLM не вызывается."""
        classifier, llm = self._make()
        assert classifier.detect("") is None
        assert classifier.detect("   ") is None
        llm.ask.assert_not_called()
        llm.classify.assert_not_called()

    def test_detect_empty_commands_no_llm_call(self):
        """Нет команд — None, LLM не вызывается."""
        classifier, llm = self._make(commands={})
        assert classifier.detect("громче") is None
        llm.ask.assert_not_called()

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
