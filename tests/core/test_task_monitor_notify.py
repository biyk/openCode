"""тесты idle-вопроса task_monitor: предложение задачи + дубль в Telegram.

Вынесено из test_task_monitor.py (тот упирается в лимит 200 строк): здесь
только то, что вопрос на idle содержит предложение незапущенной задачи и
уходит в Telegram через notify — и чего notify не трогает, когда вопроса нет.
"""

from unittest.mock import MagicMock

from lib.core.task_monitor import PROPOSE_PREFIX, QUESTION_IDLE, TaskMonitor
from lib.core.task_pick import TASKSTART_CMD_ID


class _Asker:
    """Заглушка orchestrator.ask: помнит вопрос, возвращает accepted."""

    def __init__(self, accepted=True):
        self.accepted = accepted
        self.questions = []

    def __call__(self, question, on_answer, label, timeout_s):
        self.questions.append((question, label))
        self.on_answer = on_answer
        return self.accepted


def _rows(*specs):
    return [{"task_title": t, "task_time": 10, "start_date": s,
             "task_uuid": f"u-{i}"} for i, (t, s) in enumerate(specs)]


def _monitor(mocker, rows, accepted=True, notify="default"):
    ask = _Asker(accepted=accepted)
    sink = MagicMock() if notify == "default" else notify
    monitor = TaskMonitor(ask=ask, say=mocker.MagicMock(),
                          output=mocker.MagicMock(), core=lambda text: text,
                          sheet=_sheet(rows), handler=mocker.MagicMock(),
                          notify=sink)
    return monitor, ask, sink


def _sheet(rows):
    sheet = MagicMock()
    sheet.read_all_tasks.return_value = rows
    return sheet


class TestIdleQuestionProposal:
    def test_proposes_first_not_started_task(self, mocker):
        monitor, ask, _ = _monitor(
            mocker, _rows(("Уборка", 0), ("Мытьё", 0)))
        assert monitor.tick() == "idle"
        question = ask.questions[0][0]
        assert question == f"{QUESTION_IDLE} {PROPOSE_PREFIX} Уборка"

    def test_no_proposal_when_no_titled_row(self, mocker):
        monitor, ask, _ = _monitor(mocker, _rows(("   ", 0)))
        monitor.tick()
        assert ask.questions[0][0] == QUESTION_IDLE


class TestIdleQuestionTelegram:
    def test_question_is_broadcast(self, mocker):
        monitor, ask, sink = _monitor(mocker, _rows(("Уборка", 0)))
        monitor.tick()
        sink.assert_called_once_with(ask.questions[0][0])

    def test_not_broadcast_when_deferred(self, mocker):
        """Оркестратор не принял вопрос — в чат ничего не уходит."""
        monitor, _, sink = _monitor(
            mocker, _rows(("Уборка", 0)), accepted=False)
        assert monitor.tick() == "deferred"
        sink.assert_not_called()

    def test_busy_does_not_broadcast(self, mocker):
        monitor, _, sink = _monitor(
            mocker, _rows(("Зарядка", 1_700_000_000_000)))
        assert monitor.tick() == "busy"
        sink.assert_not_called()

    def test_no_notify_is_harmless(self, mocker):
        """notify=None (дефолт) — вопрос задаётся, чат не трогается."""
        monitor, ask, _ = _monitor(mocker, _rows(("Уборка", 0)), notify=None)
        assert monitor.tick() == "idle"
        assert ask.questions[0][1] == "task_idle"


class TestIdleAnswerRecord:
    """Старт задачи по ответу на idle-вопрос идёт в статистику (мимо матчера)."""

    def _monitor_with(self, mocker, start_result):
        ask = _Asker(accepted=True)
        record = mocker.MagicMock()
        handler = mocker.MagicMock()
        handler.find_task_event.return_value = {"summary": "Уборка"}
        handler.start_task.return_value = start_result
        monitor = TaskMonitor(
            ask=ask, say=mocker.MagicMock(), output=mocker.MagicMock(),
            core=lambda text: text, sheet=_sheet(_rows(("Уборка", 0))),
            handler=handler, record=record)
        return monitor, ask, record, handler

    def test_successful_start_records(self, mocker):
        monitor, ask, record, handler = self._monitor_with(
            mocker, {"ok": True, "title": "Уборка", "row": 3})
        monitor.tick()
        ask.on_answer("уборка")
        handler.start_task.assert_called_once_with("Уборка")
        record.assert_called_once_with(TASKSTART_CMD_ID)

    def test_failed_start_does_not_record(self, mocker):
        monitor, ask, record, _ = self._monitor_with(
            mocker, {"ok": False, "error": "уже запущена"})
        monitor.tick()
        ask.on_answer("уборка")
        record.assert_not_called()

    def test_no_recorder_is_harmless(self, mocker):
        """record=None (дефолт) — старт работает, статистика не пишется."""
        ask = _Asker(accepted=True)
        handler = mocker.MagicMock()
        handler.find_task_event.return_value = {"summary": "Уборка"}
        handler.start_task.return_value = {"ok": True, "title": "Уборка",
                                           "row": 3}
        monitor = TaskMonitor(
            ask=ask, say=mocker.MagicMock(), output=mocker.MagicMock(),
            core=lambda text: text, sheet=_sheet(_rows(("Уборка", 0))),
            handler=handler)
        monitor.tick()
        ask.on_answer("уборка")     # не падает без record
        handler.start_task.assert_called_once_with("Уборка")
