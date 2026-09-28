"""Тесты фонового контроля таблицы задач (task_monitor)."""

from unittest.mock import MagicMock

from lib.core.task_monitor import (ANSWER_UNKNOWN, QUESTION_IDLE, TaskMonitor,
                                   start_task_monitor)


class _Asker:
    """Заглушка orchestrator.ask: помнит вопрос и вызывает ответ по требованию."""

    def __init__(self, accepted=True):
        self.accepted = accepted
        self.questions = []
        self.timeout_s = None

    def __call__(self, question, on_answer, label, timeout_s):
        self.questions.append((question, label))
        self.timeout_s = timeout_s
        if self.accepted:
            self.on_answer = on_answer
        return self.accepted

    def answer(self, text):
        self.on_answer(text)


def _sheet(rows):
    """Мок читалки таблицы: read_all_tasks отдаёт заранее заданные строки."""
    sheet = MagicMock()
    sheet.read_all_tasks.return_value = rows
    return sheet


def _row(title="Уборка", start=0, uuid="u-1"):
    return {"task_title": title, "task_time": 10, "start_date": start,
            "task_uuid": uuid}


def _monitor(mocker, rows, handler=None, accepted=True):
    """Монитор с мок-таблицей, мок-оркестратором и мок-исполнителем задач."""
    ask = _Asker(accepted=accepted)
    monitor = TaskMonitor(
        ask=ask, say=mocker.MagicMock(), output=mocker.MagicMock(),
        core=lambda text: text, sheet=_sheet(rows),
        handler=handler or mocker.MagicMock())
    return monitor, ask


class TestIdleQuestion:
    """Ни одной запущенной задачи → вопрос «чем занимаешься?»."""

    def test_tick_asks_idle_question(self, mocker):
        monitor, ask = _monitor(mocker, [_row(start=0)])
        assert monitor.tick() == "idle"
        assert ask.questions == [(QUESTION_IDLE, "task_idle")]
        assert ask.timeout_s == 90.0

    def test_answer_starts_matching_task(self, mocker):
        """Ответ похож на задачу таблицы → task_start по чистому заголовку."""
        handler = mocker.MagicMock()
        handler.find_task_event.return_value = {"summary": "Уборка кухни"}
        handler.start_task.return_value = {"ok": True, "title": "Уборка кухни",
                                           "row": 7}
        monitor, ask = _monitor(mocker, [_row(start=0)], handler=handler)
        monitor.tick()
        ask.answer("убираю на кухне")
        handler.find_task_event.assert_called_once_with("убираю на кухне")
        handler.start_task.assert_called_once_with("Уборка кухни")
        monitor._say.assert_called_once_with("Задача «Уборка кухни» запущена")

    def test_unknown_answer_does_not_start(self, mocker):
        """Ответ не похож ни на одну задачу — озвучиваем незнание, не стартуем."""
        handler = mocker.MagicMock()
        handler.find_task_event.return_value = None
        monitor, ask = _monitor(mocker, [_row(start=0)], handler=handler)
        monitor.tick()
        ask.answer("не знаю что")
        handler.start_task.assert_not_called()
        monitor._say.assert_called_once_with(ANSWER_UNKNOWN)

    def test_empty_answer_is_ignored(self, mocker):
        handler = mocker.MagicMock()
        monitor, ask = _monitor(mocker, [_row(start=0)], handler=handler)
        monitor.tick()
        ask.answer("   ")
        handler.find_task_event.assert_not_called()

    def test_start_failure_is_logged_only(self, mocker):
        """Задача уже запущена (ответ таблицы) — ошибки в консоль, без озвучки."""
        handler = mocker.MagicMock()
        handler.find_task_event.return_value = {"summary": "Уборка"}
        handler.start_task.return_value = {"ok": False, "error": "уже запущена"}
        monitor, ask = _monitor(mocker, [_row(start=0)], handler=handler)
        monitor.tick()
        ask.answer("уборка")
        monitor._say.assert_not_called()
        assert "уже запущена" in monitor._output.print_error.call_args.args[0]

    def test_deferred_when_orchestrator_busy(self, mocker):
        """Оркестратор не принял вопрос (уже ждём ответ) — пропуск цикла."""
        monitor, _ = _monitor(mocker, [_row(start=0)], accepted=False)
        assert monitor.tick() == "deferred"


class TestRunningTask:
    """Что-то запущено — вопросов нет, и просрочку не обсуждаем."""

    def test_running_row_is_busy_without_question(self, mocker):
        started = 1_700_000_000_000
        monitor, ask = _monitor(mocker, [_row(title="Зарядка", start=started)])
        assert monitor.tick() == "busy"
        assert ask.questions == []


class TestReadFailure:
    """Сбой чтения таблицы не должен ронять фоновый цикл."""

    def test_sheet_error_skips_tick(self, mocker):
        """Таблица не читалась (нет токена/сети) — цикла не роняем."""
        sheet = mocker.MagicMock()
        sheet.read_all_tasks.side_effect = OSError("network")
        monitor = TaskMonitor(ask=mocker.MagicMock(), say=mocker.MagicMock(),
                              output=mocker.MagicMock(), sheet=sheet)
        assert monitor.tick() == "skip"


class TestStartFromConfig:
    """Сборка монитора по секции task_monitor commands.json."""

    def _worker(self, mocker, config):
        worker = mocker.MagicMock()
        worker._matcher.get_task_monitor_config.return_value = config
        worker._matcher.core_phrase.side_effect = lambda text: text
        return worker

    def test_disabled_section_returns_none(self, mocker):
        assert start_task_monitor(self._worker(mocker, {}),
                                  mocker.MagicMock()) is None

    def test_enabled_builds_monitor_with_config(self, mocker):
        """interval_min/answer_timeout_s прокидываются в монитор."""
        worker = self._worker(mocker, {"enabled": True, "interval_min": 3,
                                       "answer_timeout_s": 15})
        started = []
        mocker.patch.object(TaskMonitor, "start",
                            side_effect=lambda: started.append(True))
        monitor = start_task_monitor(worker, mocker.MagicMock())
        assert monitor is not None
        assert started == [True]
        assert monitor._interval == 180.0
        assert monitor._answer_timeout_s == 15.0
