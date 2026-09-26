import os
import sys
from io import StringIO
from lib.core.output import TranscriptionOutput


class TestTranscriptionOutput:
    """Тесты для класса TranscriptionOutput."""

    def _make(self, tmp_path, **kwargs):
        """Создаёт output с лог-файлом во временной папке."""
        log_file = str(tmp_path / "session.log")
        return TranscriptionOutput(log_file=log_file, **kwargs), log_file

    def test_print_text_normal(self, tmp_path):
        output, _ = self._make(tmp_path)
        captured = StringIO()
        sys.stdout = captured
        output.print_text("hello")
        sys.stdout = sys.__stdout__
        assert captured.getvalue() == "hello\n"

    def test_print_text_empty(self, tmp_path):
        output, _ = self._make(tmp_path)
        captured = StringIO()
        sys.stdout = captured
        output.print_text("")
        sys.stdout = sys.__stdout__
        assert captured.getvalue() == ""

    def test_print_text_whitespace_only(self, tmp_path):
        output, _ = self._make(tmp_path)
        captured = StringIO()
        sys.stdout = captured
        output.print_text("   ")
        sys.stdout = sys.__stdout__
        assert captured.getvalue() == ""

    def test_print_info(self, tmp_path):
        output, _ = self._make(tmp_path)
        captured = StringIO()
        sys.stdout = captured
        output.print_info("test message")
        sys.stdout = sys.__stdout__
        assert captured.getvalue() == "test message\n"

    def test_print_error(self, tmp_path):
        output, _ = self._make(tmp_path)
        captured = StringIO()
        sys.stderr = captured
        output.print_error("error message")
        sys.stderr = sys.__stderr__
        assert captured.getvalue() == "error message\n"

    def test_print_stopped(self, tmp_path):
        output, _ = self._make(tmp_path)
        captured = StringIO()
        sys.stdout = captured
        output.print_stopped()
        sys.stdout = sys.__stdout__
        assert "Запись остановлена" in captured.getvalue()

    def test_print_partial_writes_without_newline(self, tmp_path):
        output, _ = self._make(tmp_path)
        captured = StringIO()
        sys.stdout = captured
        output.print_partial("частичный текст")
        sys.stdout = sys.__stdout__
        assert captured.getvalue() == "\rчастичный текст"

    def test_print_partial_empty_skips(self, tmp_path):
        output, _ = self._make(tmp_path)
        captured = StringIO()
        sys.stdout = captured
        output.print_partial("")
        sys.stdout = sys.__stdout__
        assert captured.getvalue() == ""

    def test_print_progress_with_total(self, tmp_path):
        output, _ = self._make(tmp_path)
        captured = StringIO()
        sys.stdout = captured
        output.print_progress(5, 10, prefix="Загрузка")
        sys.stdout = sys.__stdout__
        assert captured.getvalue() == "\rЗагрузка: 50.0%"

    def test_print_progress_unknown_total(self, tmp_path):
        output, _ = self._make(tmp_path)
        captured = StringIO()
        sys.stdout = captured
        output.print_progress(0, 0, prefix="Загрузка")
        sys.stdout = sys.__stdout__
        assert captured.getvalue() == "\rЗагрузка..."

    def test_init_with_color(self, tmp_path):
        output, _ = self._make(tmp_path, use_color=True)
        assert output.use_color is True

    def test_init_without_color(self, tmp_path):
        output, _ = self._make(tmp_path)
        assert output.use_color is False

    def test_log_file_contains_all_messages(self, tmp_path):
        """Все сообщения пишутся в лог-файл с метками уровней."""
        output, log_file = self._make(tmp_path)
        output.print_text("привет")
        output.print_info("deploy")
        output.print_error("boom")
        output.print_stopped()
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "[TEXT] привет" in content
        assert "[INFO] deploy" in content
        assert "[ERROR] boom" in content
        assert "[STOPPED] Запись остановлена." in content

    def test_print_debug_writes_file_only(self, tmp_path):
        """print_debug не выводит в консоль, но пишет в лог-файл."""
        output, log_file = self._make(tmp_path)
        captured = StringIO()
        sys.stdout = captured
        sys.stderr = captured
        output.print_debug("секрет отладки")
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        assert captured.getvalue() == ""
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "[DEBUG] секрет отладки" in content

    def test_empty_message_not_logged(self, tmp_path):
        """Пустые сообщения не попадают в лог-файл (файл может не создаться)."""
        output, log_file = self._make(tmp_path)
        output.print_text("")
        output.print_info("   ")
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                assert f.read() == ""

    def test_log_file_format_single_per_default_path(self, tmp_path, monkeypatch):
        """Путь по умолчанию — logs/ГГГГММДДЧЧММ.log (один на запуск)."""
        from datetime import datetime as real_dt
        from lib.core import output as output_module
        fake_dt = type(
            "FakeDT", (),
            {"now": staticmethod(lambda: real_dt(2026, 8, 31, 13, 46))},
        )
        monkeypatch.setattr(output_module, "datetime", fake_dt)
        monkeypatch.chdir(tmp_path)
        path = TranscriptionOutput()._log_file
        assert path.replace("\\", "/").endswith("202608311346.log")
        assert path.replace("\\", "/").startswith("logs/")
