"""тесты lib/core/task_pick.py — запуск задачи по нажатию кнопки Telegram."""

from unittest.mock import MagicMock

from lib.core.task_pick import make_task_picker, TASKSTART_CMD_ID


class TestMakeTaskPicker:
    def test_ok_formats_reply(self):
        handler = MagicMock()
        handler.start_task.return_value = {"ok": True, "title": "Уборка"}
        pick = make_task_picker(handler=handler)
        assert pick("уборка") == "▶️ Задача «Уборка» запущена"
        handler.start_task.assert_called_once_with("уборка")

    def test_error_reports_reason(self):
        handler = MagicMock()
        handler.start_task.return_value = {"ok": False, "error": "не найдена"}
        pick = make_task_picker(handler=handler)
        assert pick("Х") == "❌ не найдена"

    def test_swallows_exception(self, mocker):
        import lib.core.task_pick as pick_mod
        mocked = mocker.patch.object(pick_mod, "swallowed")
        handler = MagicMock()
        handler.start_task.side_effect = OSError("нет сети")
        pick = make_task_picker(handler=handler)
        assert "Не удалось" in pick("Х")
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
        assert "▶️" in pick("т")
