"""Тесты CLI засчёта задачи (python -m lib.taskflow.done_task <uuid>)."""

from lib.taskflow.done_task import _main

UUID = "f29ef6e3-f1f9-418c-a657-49ffa5dc9497"


def test_missing_uuid_exits_1_with_usage(capsys):
    """Без аргумента — подсказка и код 1."""
    assert _main([]) == 1
    assert "task_uuid" in capsys.readouterr().out


def test_success_prints_reward_and_exits_0(capsys, monkeypatch):
    """Успех: 0 и текст с названием задачи и наградой."""
    ok = {"ok": True, "title": "Пробуждение", "time_spent": 3, "money": 1.5}
    monkeypatch.setattr("lib.taskflow.done_task.mark_task_done",
                        lambda uuid, now=None: ok)
    assert _main([UUID]) == 0
    out = capsys.readouterr().out
    assert "Пробуждение" in out and "3" in out


def skipped(uuid, now=None):
    return {"ok": True, "skipped": True, "title": "Пробуждение",
            "reason": "уже засчитано сегодня"}


def test_skipped_result_is_not_an_error(capsys, monkeypatch):
    """Повторный засчёт за день — код 0, но без награды."""
    monkeypatch.setattr("lib.taskflow.done_task.mark_task_done", skipped)
    assert _main([UUID]) == 0
    assert "уже засчитана" in capsys.readouterr().out


def test_failure_and_exception_exit_1(capsys, monkeypatch):
    """ok=False и исключение — код 1 с текстом ошибки."""

    def boom(uuid, now=None):
        raise RuntimeError("нет токена")

    monkeypatch.setattr("lib.taskflow.done_task.mark_task_done", boom)
    assert _main([UUID]) == 1
    assert "нет токена" in capsys.readouterr().out

    monkeypatch.setattr(
        "lib.taskflow.done_task.mark_task_done",
        lambda uuid, now=None: {"ok": False, "error": "нет строки"})
    assert _main([UUID]) == 1
    assert "нет строки" in capsys.readouterr().out
