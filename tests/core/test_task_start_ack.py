"""Озвучка принятого старта задачи (ACK_TEXTS в lib/core/orchestrator_speech.py).

Исполнитель `python -m lib.task_start` пишет итог только в консоль, поэтому
голосовой цикл молчал: «алиса начал уход за ногтями» → EventMatch → taskstart
→ в ответ тишина. Здесь — проверка, что старт подтверждён вслух коротким
«Хорошо», а остальные ветки (завершение, чат, прочие команды) молчат как
раньше: лишняя болтовня мешает, а taskdone и сам хвалит через task_complete.
"""

from lib.core.orchestrator import Orchestrator
from lib.core.orchestrator_speech import ACK_TEXTS

UUID = "abc12345-1234-1234-1234-123456789abc"


class Sink:
    """Канал ответа текстового источника (Telegram)."""

    def __init__(self):
        self.texts = []

    def __call__(self, text):
        self.texts.append(text)


def _no_event_finder(mocker):
    """Мок подбирщика, который ничего не находит (без живого календаря)."""
    finder = mocker.MagicMock()
    finder.find_task_event.return_value = None
    return finder


def _make(mocker, core="начал уход за ногтями"):
    """Оркестратор с мок-матчером; озвучка перехвачена вместо реального TTS."""
    orch = Orchestrator(matcher=mocker.MagicMock(), output=mocker.MagicMock(),
                        tts=mocker.MagicMock())
    m = orch._matcher
    m.find_command.return_value = (None, [])
    m.missing_requires.return_value = []
    m.has_trigger.return_value = True
    m.core_phrase.return_value = core
    m.needs_text.return_value = False
    m.execute_by_id.return_value = True
    orch._event_matcher = _no_event_finder(mocker)
    orch._speak = mocker.patch.object(orch, "_speak_async")
    return orch


def _event_finder(mocker, summary="Уход за ногтями"):
    """Мок подбирщика мероприятий: всегда находит одно с uuid."""
    finder = mocker.MagicMock()
    finder.find_task_event.return_value = {"summary": summary, "colorId": ""}
    finder.event_uuid.return_value = UUID
    return finder


def _spoken(orch):
    """Что оркестратор собирался произнести вслух (в порядке вызовов)."""
    return [c.args[0] for c in orch._speak.call_args_list]


class TestAckTable:
    """Что озвучивается, а что нет — по таблице ACK_TEXTS."""

    def test_taskstart_acked(self):
        assert ACK_TEXTS["taskstart"] == "Хорошо"

    def test_taskdone_not_acked(self):
        """Похвала «Вы умничка!» идёт из lib/task_complete.py: второй раз
        то же самое слушателю незачем."""
        assert "taskdone" not in ACK_TEXTS

    def test_plain_commands_stay_silent(self):
        assert not any(k in ACK_TEXTS for k in ("playpause", "openyoutube"))


class TestEventMatchStart:
    """Тот самый путь из лога: нераспознанная фраза → событие → taskstart."""

    def test_start_is_spoken_aloud(self, mocker):
        orch = _make(mocker)
        orch._event_matcher = _event_finder(mocker)
        orch.process_text("алиса начал уход за ногтями")
        assert _spoken(orch) == ["Хорошо"]

    def test_complete_stays_silent(self, mocker):
        orch = _make(mocker, core="закончил уход за ногтями")
        orch._event_matcher = _event_finder(mocker)
        orch.process_text("алиса закончил уход за ногтями")
        assert orch._matcher.execute_by_id.call_args.args[0] == "taskdone"
        assert _spoken(orch) == []

    def test_failure_is_not_acked(self, mocker):
        """Старт не состоялся (задача уже запущена) — подтверждать нечего."""
        orch = _make(mocker)
        orch._event_matcher = _event_finder(mocker)
        orch._matcher.execute_by_id.return_value = False
        orch.process_text("алиса начал уход за ногтями")
        assert _spoken(orch) == []


class TestOtherStartPaths:
    """Старт по другой ветке подтверждается ровно один раз."""

    def test_literal_command_acked_once(self, mocker):
        """Дословный taskstart из commands.json — одно «Хорошо», не два."""
        orch = _make(mocker, core="я начал уборку")
        orch._matcher.find_command.return_value = ("taskstart", ())
        orch.process_text("алиса я начал уборку")
        assert _spoken(orch) == ["Хорошо"]

    def test_knowledge_action_start_acked(self, mocker):
        """Подтверждённая доской мероприятная фраза — тоже старт вслух."""
        orch = _make(mocker)
        assert orch._execute_event_action("start", "Уход за ногтями") is True
        assert _spoken(orch) == ["Хорошо"]

    def test_chat_gets_no_voice_and_no_duplicate(self, mocker):
        """В чате подтверждение уже есть («Выполнено: taskstart»): динамики
        молчат и второе сообщение сверху не приходит."""
        orch = _make(mocker)
        orch._matcher.find_command.return_value = ("taskstart", ())
        sink = Sink()
        orch.process_text("алиса я начал уборку", reply=sink)
        assert sink.texts == ["Выполнено: taskstart"]
        assert _spoken(orch) == []
