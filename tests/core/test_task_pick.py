"""тесты lib/core/task_pick.py — запуск задачи по нажатию кнопки Telegram."""

from unittest.mock import MagicMock, patch

from lib.core.task_pick import make_task_picker, TASKSTART_CMD_ID


class TestMakeTaskPicker:
    def test_ok_formats_reply_and_offers_finish(self):
        handler = MagicMock()
        handler.start_task.return_value = {"ok": True, "title": "Уборка"}
        pick = make_task_picker(handler=handler)
        assert pick("уборка") == ("▶️ Задача «Уборка» запущена", "Уборка")
        handler.start_task.assert_called_once_with("уборка")

    def test_error_reports_reason_no_finish(self):
        handler = MagicMock()
        handler.start_task.return_value = {"ok": False, "error": "не найдена"}
        pick = make_task_picker(handler=handler)
        assert pick("Х") == ("❌ не найдена", None)

    def test_swallows_exception(self, mocker):
        import lib.core.task_pick as pick_mod
        mocked = mocker.patch.object(pick_mod, "swallowed")
        handler = MagicMock()
        handler.start_task.side_effect = OSError("нет сети")
        pick = make_task_picker(handler=handler)
        text, ft = pick("Х")
        assert "Не удалось" in text
        assert ft is None
        mocked.assert_called_once()

    def test_records_taskstart_on_ok(self):
        handler = MagicMock()
        handler.start_task.return_value = {"ok": True, "title": "Уборка"}
        record = MagicMock()
        pick = make_task_picker(handler=handler, record=record)
        pick("уборка")
        record.assert_called_once_with(TASKSTART_CMD_ID)

    def test_does_not_record_on_failure(self):
        handler = MagicMock()
        handler.start_task.return_value = {"ok": False, "error": "нет"}
        record = MagicMock()
        pick = make_task_picker(handler=handler, record=record)
        pick("Х")
        record.assert_not_called()

    def test_no_recorder_is_ok(self):
        handler = MagicMock()
        handler.start_task.return_value = {"ok": True, "title": "Т"}
        pick = make_task_picker(handler=handler)   # record=None по умолчанию
        text, _ = pick("т")
        assert "▶️" in text

    def test_title_falls_back_to_input_when_no_summary(self):
        """Старт без `title` в ответе handler'а: finish всё равно есть."""
        handler = MagicMock()
        handler.start_task.return_value = {"ok": True}
        pick = make_task_picker(handler=handler)
        text, ft = pick("уборка")
        assert ft == "уборка"
        assert "уборка" in text

    def test_handler_is_recreated_per_click(self):
        """Без инжекта prod-путь строит Новый handler на клик.

        `TaskStartHandler` фиксирует `now` в `__init__`; кэш ставил бы
        устаревший `start_date` (клик в 07:46 использовался бы для старта
        «утренней зарядки» в 08:19 — та же ошибка, что ловили в monitor).
        """
        h1, h2 = MagicMock(), MagicMock()
        h1.start_task.return_value = {"ok": True, "title": "Ч"}
        h2.start_task.return_value = {"ok": True, "title": "З"}
        with patch("lib.core.task_pick.TaskStartHandler",
                   side_effect=[h1, h2]) as factory:
            pick = make_task_picker()             # handler=None → прод-путь
            pick("чистить зубы")
            pick("утренняя зарядка")
        assert factory.call_count == 2
        h1.start_task.assert_called_once_with("чистить зубы")
        h2.start_task.assert_called_once_with("утренняя зарядка")
