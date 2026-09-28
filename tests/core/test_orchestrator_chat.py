"""Тесты чат-канала оркестратора (lib/core/orchestrator_chat.py).

Запрос из чата (Telegram) отличается от строки микрофона двумя вещами: его не
нужно защищать окном эхо-затишья/озвучки (это не звук с колонок) и отвечать
ему надо текстом в тот же канал, а не вслух. Проверяем, что оба выполнены и
что голосовой путь остался как раньше.
"""

import time

from lib.core.orchestrator import Orchestrator


class Sink:
    """Канал ответа: собирает текст, который оркестратор послал источнику."""

    def __init__(self, fail=False):
        self.texts = []
        self._fail = fail

    def __call__(self, text):
        self.texts.append(text)
        if self._fail:
            raise RuntimeError("чат недоступен")


def _make(mocker, **kwargs):
    """Оркестратор с мок-зависимостями (как в test_orchestrator)."""
    orch = Orchestrator(matcher=mocker.MagicMock(), output=mocker.MagicMock(),
                        tts=mocker.MagicMock(), **kwargs)
    m = orch._matcher
    m.find_command.return_value = (None, [], False)
    m.missing_requires.return_value = []
    m.has_trigger.return_value = True
    m.core_phrase.return_value = "пауза"
    m.execute_by_id.return_value = True
    m.need_message.side_effect = lambda name: f"Включи {name}"
    m.needs_text.return_value = True
    orch._speak = mocker.patch.object(orch, "_speak_async")
    return orch


class TestGates:
    def test_command_replies_done_without_tts(self, mocker):
        orch = _make(mocker)
        orch._matcher.find_command.return_value = ("playpause", [], False)
        sink = Sink()
        orch.process_text("пожалуйста пауза", reply=sink)
        assert sink.texts == ["Выполнено: playpause"]
        assert orch._speak.called is False
        assert orch.speaking is False

    def test_failed_command_is_reported_to_chat(self, mocker):
        orch = _make(mocker)
        orch._matcher.find_command.return_value = ("playpause", [], False)
        orch._matcher.execute_by_id.return_value = False
        sink = Sink()
        orch.process_text("пожалуйста пауза", reply=sink)
        assert sink.texts == ["Команда «playpause» не выполнена"]

    def test_chat_ignores_suppress_window(self, mocker):
        """Строка чата — не эхо колонок: окно затишья её не тормозит."""
        orch = _make(mocker)
        orch._matcher.find_command.return_value = ("playpause", [], False)
        orch._suppress_until = time.monotonic() + 60
        sink = Sink()
        orch.process_text("пожалуйста пауза", reply=sink)
        orch._output.print_text.assert_called_once_with("пожалуйста пауза")
        assert sink.texts == ["Выполнено: playpause"]

    def test_chat_ignores_speaking_gate(self, mocker):
        """Пока идёт озвучка, чат всё равно исполняет команду."""
        orch = _make(mocker)
        orch._matcher.find_command.return_value = ("playpause", [], False)
        orch._speaking = True
        sink = Sink()
        orch.process_text("пожалуйста пауза", reply=sink)
        assert sink.texts == ["Выполнено: playpause"]
        assert orch._speak.called is False

    def test_voice_request_clears_channel(self, mocker):
        """Следующий голосовой запрос снимает канал (фоновые ответы не в чат)."""
        orch = _make(mocker)
        orch._matcher.has_trigger.return_value = False
        orch.process_text("пожалуйста пауза", reply=Sink())
        assert orch._reply is not None
        orch.process_text("привет")
        assert orch._reply is None

    def test_processing_is_serialized(self, mocker):
        """Пайплайн идёт под замком: чат и микрофон не перемешиваются."""
        orch = _make(mocker)
        seen = {}

        def find(_lines):
            got = orch._input_lock.acquire(blocking=False)
            seen["free"] = got
            if got:
                orch._input_lock.release()
            return (None, [], False)

        orch._matcher.find_command.side_effect = find
        orch.process_text("пожалуйста пауза", reply=Sink())
        assert seen["free"] is False


class TestSayRouting:
    def test_say_goes_to_chat(self, mocker):
        orch = _make(mocker)
        sink = Sink()
        orch._begin_request(sink)
        orch._say("Готово")
        assert sink.texts == ["Готово"]
        assert orch._speak.called is False

    def test_say_without_channel_still_tts(self, mocker):
        orch = _make(mocker)
        orch._begin_request(None)
        orch._say("Готово")
        assert orch._speak.called is True

    def test_blocked_needs_message_to_chat(self, mocker):
        orch = _make(mocker)
        sink = Sink()
        orch._begin_request(sink)
        orch._report_blocked("openyoutube", ["browser_youtube"])
        assert sink.texts == ["Включи browser_youtube"]
        assert orch._speak.called is False

    def test_dev_mode_is_voice_only(self, mocker):
        """Управление dev-режимом из чата отвергается (оно про микрофон)."""
        orch = _make(mocker)
        orch._matcher.core_phrase.return_value = "режим разработки"
        sink = Sink()
        orch.process_text("алиса режим разработки", reply=sink)
        assert orch.dev_mode is False
        assert sink.texts == ["Режим разработки — только голосом"]


class TestLevelReports:
    def test_not_recognized_is_not_silent(self, mocker):
        """Промах Лайи и LLM в чате виден: иначе молчание непонятно."""
        decision = mocker.MagicMock()
        decision.detect.return_value = None
        orch = _make(mocker, decision=decision)
        mocker.patch.object(orch, "_try_event_match", return_value=False)
        sink = Sink()
        orch.process_text("пожалуйста фуфулу", reply=sink)
        assert sink.texts == ["Команда не распознана"]

    def test_event_action_replies_done(self, mocker):
        orch = _make(mocker)
        sink = Sink()
        orch._begin_request(sink)
        assert orch._execute_event_action("complete", "Зарядка") is True
        assert sink.texts == ["Выполнено: taskdone"]

    def test_async_answer_follows_its_requester(self, mocker):
        """Фоновый итог opencode уходит заказчику, а не текущему источнику."""
        opencode = mocker.MagicMock()
        opencode.run.return_value = "Готово"
        orch = _make(mocker, opencode=opencode)
        sink = Sink()
        orch._begin_request(sink)
        orch._enqueue_opencode("вопрос")
        orch._begin_request(None)        # параллельно пришла голосовая строка
        orch._opencode_queue.join()
        assert sink.texts == ["Готово"]
        assert orch._speak.called is False

    def test_sink_failure_is_swallowed(self, mocker):
        """Сбой отправки не роняет обработку команды."""
        log = mocker.patch("lib.core.orchestrator_chat.swallowed")
        orch = _make(mocker)
        orch._matcher.find_command.return_value = ("playpause", [], False)
        orch.process_text("пожалуйста пауза", reply=Sink(fail=True))
        assert log.call_args.args[0] == "chat.reply"
        orch._matcher.execute_by_id.assert_called_once()
