"""Тесты Orchestrator: вопрос вслух и перехват строки-ответа."""

import time
from lib.core.orchestrator import Orchestrator


def _make(mocker, **kwargs):
    """Оркестратор с мок-зависимостями и заглушкой озвучки."""
    defaults = {
        "matcher": mocker.MagicMock(),
        "output": mocker.MagicMock(),
        "tts": mocker.MagicMock(),
    }
    defaults.update(kwargs)
    orch = Orchestrator(**defaults)
    if "matcher" not in kwargs:
        orch._matcher.find_command.return_value = (None, [])
        orch._matcher.has_trigger.return_value = False
        orch._matcher.core_phrase.side_effect = lambda text: text
    mocker.patch.object(orch, "_say")
    mocker.patch.object(orch, "_process_commands_level")
    return orch


class TestAsk:
    """Задание вопроса и ожидание ответа."""

    def test_ask_speaks_and_pends(self, mocker):
        """Вопрос озвучен, колбэк ждёт следующую строку."""
        orch = _make(mocker)
        answer = mocker.MagicMock()
        assert orch.ask("Чем ты сейчас занимаешься?", answer,
                        "task_idle") is True
        orch._say.assert_called_once_with("Чем ты сейчас занимаешься?")
        assert orch.pending_ask == "task_idle"

    def test_ask_defers_while_answer_pending(self, mocker):
        """Вопрос на вопрос не накладывается: второй отклонён."""
        orch = _make(mocker)
        assert orch.ask("Первый", mocker.MagicMock(), "one") is True
        assert orch.ask("Второй", mocker.MagicMock(), "two") is False
        assert orch.pending_ask == "one"

    def test_ask_defers_while_speaking(self, mocker):
        """Пока идёт озвучка, вопрос откладывается (не режет ответ TTS)."""
        orch = _make(mocker)
        orch._speaking = True
        assert orch.ask("Первый", mocker.MagicMock(), "one") is False
        assert orch.pending_ask is None

    def test_expired_question_frees_next_ask(self, mocker):
        """Вопрос без ответа просрочен — следующий задаётся, а не откладывается."""
        orch = _make(mocker)
        first = mocker.MagicMock()
        orch.ask("Первый", first, "one")
        orch._pending_ask.deadline = time.monotonic() - 1
        assert orch.ask("Второй", mocker.MagicMock(), "two") is True
        assert orch.pending_ask == "two"
        first.assert_not_called()


class TestAnswerInterception:
    """Следующая строка после вопроса — ответ, а не команда."""

    def test_answer_goes_to_callback_not_pipeline(self, mocker):
        """Строка отдана колбэку, пайплайн команд её не видит."""
        orch = _make(mocker)
        answer = mocker.MagicMock()
        orch.ask("Чем ты сейчас занимаешься?", answer, "task_idle")
        orch.process_text("убираю на кухне")
        answer.assert_called_once_with("убираю на кухне")
        orch._process_commands_level.assert_not_called()
        assert orch.pending_ask is None

    def test_without_pending_question_pipeline_runs(self, mocker):
        """Без вопроса строка идёт обычный путь."""
        orch = _make(mocker)
        orch.process_text("привет")
        orch._process_commands_level.assert_called_once_with("привет")

    def test_expired_answer_returns_to_pipeline(self, mocker):
        """Просроченный вопрос снимается: строка снова обычная речь."""
        orch = _make(mocker)
        answer = mocker.MagicMock()
        orch.ask("Вопрос?", answer, "task_idle")
        orch._pending_ask.deadline = time.monotonic() - 1
        orch.process_text("привет")
        answer.assert_not_called()
        orch._process_commands_level.assert_called_once_with("привет")

    def test_stop_word_cancels_without_callback(self, mocker):
        """«стоп» снимает вопрос и не считается ответом."""
        orch = _make(mocker)
        answer = mocker.MagicMock()
        orch.ask("Вопрос?", answer, "task_idle")
        orch.process_text("стоп")
        answer.assert_not_called()
        orch._process_commands_level.assert_not_called()
        assert orch.pending_ask is None

    def test_answer_error_does_not_break_loop(self, mocker):
        """Исключение в обработке ответа не роняет цикл STT."""
        orch = _make(mocker)
        orch.ask("Вопрос?", mocker.MagicMock(side_effect=RuntimeError("boom")),
                 "task_idle")
        orch.process_text("урок английского")
        orch._process_commands_level.assert_not_called()

    def test_stop_clears_pending_question(self, mocker):
        """Остановка оркестратора снимает ожидаемый вопрос."""
        orch = _make(mocker)
        orch.ask("Вопрос?", mocker.MagicMock(), "task_idle")
        orch.stop()
        assert orch.pending_ask is None
