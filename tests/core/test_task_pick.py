"""тесты lib/core/task_pick.py — запуск задачи по нажатию кнопки Telegram."""

from unittest.mock import MagicMock

from lib.core.task_pick import make_task_picker


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
