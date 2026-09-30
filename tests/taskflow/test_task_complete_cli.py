"""Тесты CLI завершения задачи (python -m lib.task_complete ["название"])."""

import pytest

from lib.task_complete import _main

UUID = "6a1c2d3e-4f50-5152-a3a4-b5c6d7e8f901"


@pytest.fixture(autouse=True)
def spoken(monkeypatch):
    """Пишет озвученные фразы; глушит реальный TTS и поход в календарь.

    Autouse: ни один тест CLI не должен дёргать синтез речи или OAuth —
    «следующая задача» по умолчанию None, нужный тест переопределяет сам.
    """
    said = []

    class FakeTTS:
        def speak_blocks(self, blocks, **kw):
            said.append(" ".join(blocks))

    monkeypatch.setattr("lib.tts.TextToSpeech", FakeTTS)
    monkeypatch.setattr("lib.task_complete.TaskCompleteHandler.next_task",
                        lambda self, done_uuid=None: None)
    return said


def _ok(res, monkeypatch):
    monkeypatch.setattr("lib.task_complete.TaskCompleteHandler"
                        ".complete_task", lambda self, name: res)


def test_stop_branch_prints_elapsed(capsys, monkeypatch):
    _ok({"ok": True, "branch": "⏹", "title": "Велосипед",
         "elapsed_minutes": 5, "money": 1.0}, monkeypatch)
    assert _main(["починить велосипед"]) == 0
    out = capsys.readouterr().out
    assert "⏹" in out and "Велосипед" in out and "5 мин" in out


def test_done_branch_prints_plan(capsys, monkeypatch):
    _ok({"ok": True, "branch": "✅", "title": "Отчёт",
         "time_spent": 3, "money": 1.5}, monkeypatch)
    assert _main([]) == 0
    assert "✅" in capsys.readouterr().out


def test_skipped_is_not_error(capsys, monkeypatch):
    _ok({"ok": True, "skipped": True, "title": "Пробуждение"}, monkeypatch)
    assert _main(["пробуждение"]) == 0
    assert "уже засчитана" in capsys.readouterr().out


def test_error_and_exception_exit_1(capsys, monkeypatch):
    _ok({"ok": False, "error": "нет запущенной задачи"}, monkeypatch)
    assert _main([""]) == 1
    assert "нет запущенной" in capsys.readouterr().out

    def boom(self, name):
        raise RuntimeError("нет токена")

    monkeypatch.setattr("lib.task_complete.TaskCompleteHandler"
                        ".complete_task", boom)
    assert _main([UUID]) == 1
    assert "нет токена" in capsys.readouterr().out


def test_done_is_announced_with_praise(spoken, monkeypatch):
    """Завершение озвучивается: название задачи + похвала."""
    _ok({"ok": True, "branch": "✅", "title": "Отчёт",
         "time_spent": 3, "money": 1.5, "uuid": UUID}, monkeypatch)
    assert _main([]) == 0
    assert spoken, "ничего не озвучено"
    said = spoken[-1]
    assert "Отчёт" in said and "выполнена" in said and "умничка" in said


def test_next_task_is_announced(spoken, monkeypatch):
    """Если есть следующее мероприятие — его называют после похвалы."""
    monkeypatch.setattr(
        "lib.task_complete.TaskCompleteHandler.next_task",
        lambda self, done_uuid=None: {"summary": "Полить цветы"})
    _ok({"ok": True, "branch": "⏹", "title": "Велосипед",
         "elapsed_minutes": 5, "money": 1.0, "uuid": UUID}, monkeypatch)
    assert _main(["велосипед"]) == 0
    assert "Следующая задача: Полить цветы" in spoken[-1]


def test_no_next_task_not_announced(spoken, monkeypatch):
    """Будущих задач нет (autouse next_task=None) — фразы «Следующая» нет."""
    _ok({"ok": True, "branch": "✅", "title": "Отчёт",
         "time_spent": 3, "money": 1.5, "uuid": UUID}, monkeypatch)
    assert _main([]) == 0
    assert "Следующая" not in spoken[-1]
