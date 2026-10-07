"""тесты lib/core/task_finish.py — завершение задачи по кнопке Telegram."""

from unittest.mock import MagicMock, patch

from lib.core.task_finish import make_task_finisher, TASKDONE_CMD_ID


class TestMakeTaskFinisher:
    def test_stop_branch_reports_elapsed(self):
        handler = MagicMock()
        handler.complete_task.return_value = {
            "ok": True, "branch": "⏹", "title": "Уборка",
            "elapsed_minutes": 12, "money": 3.5,
        }
        finish = make_task_finisher(handler=handler)
        assert finish("уборка") == (
            "⏹ Задача «Уборка» завершена: 12 мин, награда 3.50")
        handler.complete_task.assert_called_once_with("уборка")

    def test_done_branch_reports_planned(self):
        handler = MagicMock()
        handler.complete_task.return_value = {
            "ok": True, "branch": "✅", "title": "Зарядка",
            "time_spent": 20, "money": 1.0,
        }
        finish = make_task_finisher(handler=handler)
        assert finish("зарядка") == (
            "✅ Задача «Зарядка» засчитана: 20 мин, награда 1.00")

    def test_skipped_is_not_error(self):
        handler = MagicMock()
        handler.complete_task.return_value = {
            "ok": True, "skipped": True, "title": "Уборка",
        }
        finish = make_task_finisher(handler=handler)
        assert finish("уборка") == "✅ «Уборка» уже засчитана сегодня"

    def test_error_reports_reason(self):
        handler = MagicMock()
        handler.complete_task.return_value = {
            "ok": False, "error": "нет запущенной задачи",
        }
        finish = make_task_finisher(handler=handler)
        assert finish("") == "❌ нет запущенной задачи"

    def test_missing_error_uses_title_fallback(self):
        handler = MagicMock()
        handler.complete_task.return_value = {"ok": False}
        finish = make_task_finisher(handler=handler)
        assert "«Уборка»" in finish("Уборка")

    def test_swallows_exception(self, mocker):
        import lib.core.task_finish as fin_mod
        mocked = mocker.patch.object(fin_mod, "swallowed")
        handler = MagicMock()
        handler.complete_task.side_effect = OSError("нет сети")
        finish = make_task_finisher(handler=handler)
        assert "Не удалось завершить" in finish("Уборка")
        mocked.assert_called_once()

    def test_records_taskdone_on_ok(self):
        handler = MagicMock()
        handler.complete_task.return_value = {
            "ok": True, "branch": "⏹", "title": "У", "elapsed_minutes": 1,
            "money": 0.0,
        }
        record = MagicMock()
        finish = make_task_finisher(handler=handler, record=record)
        finish("у")
        record.assert_called_once_with(TASKDONE_CMD_ID)

    def test_does_not_record_on_failure(self):
        handler = MagicMock()
        handler.complete_task.return_value = {"ok": False, "error": "x"}
        record = MagicMock()
        finish = make_task_finisher(handler=handler, record=record)
        finish("Х")
        record.assert_not_called()

    def test_no_recorder_is_ok(self):
        handler = MagicMock()
        handler.complete_task.return_value = {
            "ok": True, "branch": "✅", "title": "Т",
            "time_spent": 1, "money": 0.0,
        }
        finish = make_task_finisher(handler=handler)   # record=None
        assert "✅" in finish("т")

    def test_handler_is_recreated_per_click(self):
        """Без инжекта prod-путь строит Новый handler на клик.

        `TaskCompleteHandler` фиксирует `now` в `__init__`; кэш считал бы
        длительность отрезка от старого момента — тот же класс бага, что
        и `task_pick._handler` / `task_monitor._task_handler`.
        """
        h1, h2 = MagicMock(), MagicMock()
        h1.complete_task.return_value = {
            "ok": True, "branch": "⏹", "title": "Ч", "elapsed_minutes": 1,
            "money": 0.0,
        }
        h2.complete_task.return_value = {
            "ok": True, "branch": "⏹", "title": "З", "elapsed_minutes": 1,
            "money": 0.0,
        }
        with patch("lib.core.task_finish.TaskCompleteHandler",
                   side_effect=[h1, h2]) as factory:
            finish = make_task_finisher()         # handler=None → прод-путь
            finish("чистить зубы")
            finish("утренняя зарядка")
        assert factory.call_count == 2
        h1.complete_task.assert_called_once_with("чистить зубы")
        h2.complete_task.assert_called_once_with("утренняя зарядка")
