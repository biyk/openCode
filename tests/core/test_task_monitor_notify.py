"""тесты idle-вопроса task_monitor: предложение задачи + дубль в Telegram.

Вынесено из test_task_monitor.py (тот упирается в лимит 200 строк): здесь
только то, что вопрос на idle содержит предложение незапущенной задачи и
уходит в Telegram через notify — и чего notify не трогает, когда вопроса нет.
"""

from unittest.mock import MagicMock

from lib.core.task_monitor import PROPOSE_PREFIX, QUESTION_IDLE, TaskMonitor


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
