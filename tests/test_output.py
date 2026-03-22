import pytest
import sys
from io import StringIO
from lib.output import TranscriptionOutput


class TestTranscriptionOutput:
    """Тесты для класса TranscriptionOutput."""

    def test_print_text_normal(self):
        output = TranscriptionOutput()
        captured = StringIO()
        sys.stdout = captured
        output.print_text("hello")
        sys.stdout = sys.__stdout__
        assert captured.getvalue() == "hello\n"

    def test_print_text_empty(self):
        output = TranscriptionOutput()
        captured = StringIO()
        sys.stdout = captured
        output.print_text("")
        sys.stdout = sys.__stdout__
        assert captured.getvalue() == ""

    def test_print_text_whitespace_only(self):
        output = TranscriptionOutput()
        captured = StringIO()
        sys.stdout = captured
        output.print_text("   ")
        sys.stdout = sys.__stdout__
        assert captured.getvalue() == ""

    def test_print_info(self):
        output = TranscriptionOutput()
        captured = StringIO()
        sys.stdout = captured
        output.print_info("test message")
        sys.stdout = sys.__stdout__
        assert captured.getvalue() == "test message\n"

    def test_print_error(self):
        output = TranscriptionOutput()
        captured = StringIO()
        sys.stderr = captured
        output.print_error("error message")
        sys.stderr = sys.__stderr__
        assert captured.getvalue() == "error message\n"

    def test_print_stopped(self):
        output = TranscriptionOutput()
        captured = StringIO()
        sys.stdout = captured
        output.print_stopped()
        sys.stdout = sys.__stdout__
        assert "Запись остановлена" in captured.getvalue()

    def test_init_with_color(self):
        output = TranscriptionOutput(use_color=True)
        assert output.use_color is True

    def test_init_without_color(self):
        output = TranscriptionOutput()
        assert output.use_color is False
