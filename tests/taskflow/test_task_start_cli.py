# TOOLTIP: Тесты CLI запуска задачи: ok/err/пустое имя + рамка вокруг сетевых сбоев (без traceback)
"""Тесты CLI `python -m lib.task_start "название"`.

Ловим регресс, из-за которого временный DNS-сбой на googleapis dump'ил
полный traceback в консоль: пользователь видел «что-то сломалось», хотя
окружение просто на секунду отвалось. Рамка `try/except` в `_main`
обязана печатать короткую строку `[start] ошибка запуска: ...` и
возвращать rc=1 (как в `task_complete.py`).
"""

from lib.task_start import _main

UUID = "6a1c2d3e-4f50-5152-a3a4-b5c6d7e8f901"


def _ok(result, monkeypatch):
    monkeypatch.setattr(
        "lib.task_start.TaskStartHandler.start_task",
        lambda self, name: result)


class TestHappyAndErrorPaths:
    def test_ok_prints_started_line(self, capsys, monkeypatch):
        _ok({"ok": True, "title": "Зарядка", "uuid": UUID,
             "row": 5, "new_start": 1700000000000}, monkeypatch)
        assert _main(["утренняя зарядка"]) == 0
        out = capsys.readouterr().out
        assert "▶️" in out and "Зарядка" in out and "5" in out

    def test_error_dict_prints_message(self, capsys, monkeypatch):
        _ok({"ok": False, "error": "задача «Мythe» не найдена"}, monkeypatch)
        assert _main(["Мythe"]) == 1
        assert "не найдена" in capsys.readouterr().out

    def test_empty_name_usage(self, capsys):
        assert _main([""]) == 1
        assert "Укажите название" in capsys.readouterr().out


class TestNetworkCrashIsContained:
    """Сетевой сбой (DNS/httplib2/OSError) НЕ должен dump'ить traceback.

    Причина: голос «алиса начал … задачу» вызывает subprocess
    `python -m lib.task_start`, а `_main` раньше не обёртывал вызов
    `start_task`. При `httplib2.ServerNotFoundError` Python печатал
    полный traceback, и юзер видел «что-то упало», хотя на деле
    сеть на секунду дрогнула.
    """

    def test_dns_failure_returns_1_not_traceback(self, capsys, monkeypatch):
        def boom(self, name):
            raise OSError("[Errno 11002] getaddrinfo failed")

        monkeypatch.setattr(
            "lib.task_start.TaskStartHandler.start_task", boom)
        assert _main(["любая задача"]) == 1
        out = capsys.readouterr().out
        # Короткая строка есть, traceback'а нет
        assert "[start] ошибка запуска" in out
        assert "Traceback" not in out
        assert "getaddrinfo failed" in out       # суть ошибки видна

    def test_httplib_server_not_found_captured(self, capsys, monkeypatch):
        """Похожий кейс с текстом, близким к реальному 10:19:43."""
        def boom(self, name):
            raise RuntimeError(
                "Unable to find the server at www.googleapis.com")

        monkeypatch.setattr(
            "lib.task_start.TaskStartHandler.start_task", boom)
        assert _main(["глобальный задачу"]) == 1
        out = capsys.readouterr().out
        assert "Unable to find the server" in out
        assert "Traceback" not in out
