"""Тесты CLI завершения задачи (python -m lib.task_complete ["название"])."""

from lib.task_complete import _main

UUID = "6a1c2d3e-4f50-5152-a3a4-b5c6d7e8f901"


def test_stop_branch_prints_elapsed(capsys, monkeypatch):
    res = {"ok": True, "branch": "⏹", "title": "Велосипед",
           "elapsed_minutes": 5, "money": 1.0}
    monkeypatch.setattr("lib.task_complete.TaskCompleteHandler"
                        ".complete_task", lambda self, name: res)
    assert _main(["починить велосипед"]) == 0
    out = capsys.readouterr().out
    assert "⏹" in out and "Велосипед" in out and "5 мин" in out


def test_done_branch_prints_plan(capsys, monkeypatch):
    res = {"ok": True, "branch": "✅", "title": "Отчёт",
           "time_spent": 3, "money": 1.5}
    monkeypatch.setattr("lib.task_complete.TaskCompleteHandler"
                        ".complete_task", lambda self, name: res)
    assert _main([]) == 0
    assert "✅" in capsys.readouterr().out


def test_skipped_is_not_error(capsys, monkeypatch):
    res = {"ok": True, "skipped": True, "title": "Пробуждение"}
    monkeypatch.setattr("lib.task_complete.TaskCompleteHandler"
                        ".complete_task", lambda self, name: res)
    assert _main(["пробуждение"]) == 0
    assert "уже засчитана" in capsys.readouterr().out


def test_error_and_exception_exit_1(capsys, monkeypatch):
    res = {"ok": False, "error": "нет запущенной задачи"}
    monkeypatch.setattr("lib.task_complete.TaskCompleteHandler"
                        ".complete_task", lambda self, name: res)
    assert _main([""]) == 1
    assert "нет запущенной" in capsys.readouterr().out

    def boom(self, name):
        raise RuntimeError("нет токена")

    monkeypatch.setattr("lib.task_complete.TaskCompleteHandler"
                        ".complete_task", boom)
    assert _main([UUID]) == 1
    assert "нет токена" in capsys.readouterr().out
