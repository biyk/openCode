"""Тесты обёртки консоли TimestampedStream: метка времени на каждой строке.

Отдельно от test_output.py (лимит длины): там TranscriptionOutput, здесь —
поток-обёртка, которую main.py и CLI-точки входа (`python -m lib.…`) ставят
на sys.stdout/sys.stderr.
"""
import sys
from datetime import datetime
from io import StringIO

from lib.core import output as output_module
from lib.core.output import TimestampedStream, stamp_stdio


def _fixed_clock(monkeypatch):
    """Фиксирует datetime в модуле output на 13:46:07."""
    fake = type("FakeDT", (), {
        "now": staticmethod(lambda: datetime(2026, 8, 31, 13, 46, 7)),
    })
    monkeypatch.setattr(output_module, "datetime", fake)


class TestTimestampedStream:
    """Каждая новая строка получает [ЧЧ:ММ:СС] , пустые — нет."""

    def test_first_line_stamped(self, monkeypatch):
        _fixed_clock(monkeypatch)
        buf = StringIO()
        stream = TimestampedStream(buf)
        print("[TTS] Воспроизведение завершено", file=stream)
        assert buf.getvalue() == "[13:46:07] [TTS] Воспроизведение завершено\n"

    def test_each_newline_resets_stamp(self, monkeypatch):
        """Две строки одним write — обе с меткой."""
        _fixed_clock(monkeypatch)
        buf = StringIO()
        stream = TimestampedStream(buf)
        stream.write("раз\nдва\n")
        assert buf.getvalue() == "[13:46:07] раз\n[13:46:07] два\n"

    def test_continuation_line_not_restamped(self, monkeypatch):
        """Без перевода строки следующая запись — та же строка, без метки."""
        _fixed_clock(monkeypatch)
        buf = StringIO()
        stream = TimestampedStream(buf)
        stream.write("начало ")
        stream.write("продолжение\n")
        assert buf.getvalue() == "[13:46:07] начало продолжение\n"

    def test_leading_blank_line_not_stamped(self, monkeypatch):
        """Пустая строка (\\n) метки не получает, следующая — получает."""
        _fixed_clock(monkeypatch)
        buf = StringIO()
        stream = TimestampedStream(buf)
        stream.write("\nтекст\n")
        assert buf.getvalue() == "\n[13:46:07] текст\n"

    def test_empty_write_passthrough(self):
        buf = StringIO()
        stream = TimestampedStream(buf)
        assert stream.write("") == 0
        assert buf.getvalue() == ""

    def test_non_str_passthrough(self):
        """Bytes (например, буфер) уходит внутреннему потоку как есть."""
        captured = []

        class BytesSink:
            def write(self, data):
                captured.append(data)
                return len(data)

        TimestampedStream(BytesSink()).write(b"\x00\x01")
        assert captured == [b"\x00\x01"]

    def test_flush_proxies_to_underlying(self):
        calls = []

        class Sink:
            def write(self, data):
                return len(data)

            def flush(self):
                calls.append("flush")

        TimestampedStream(Sink()).flush()
        assert calls == ["flush"]

    def test_getattr_proxies_to_underlying(self):
        """Не известные обёртке атрибуты (getvalue/writable) — внутреннему."""
        buf = StringIO()
        stream = TimestampedStream(buf)
        stream.write("данные\n")
        assert stream.getvalue() == buf.getvalue()
        assert stream.writable() == buf.writable()

    def test_default_line_start_is_true(self, monkeypatch):
        """Свежий поток печатает метку с первой же строки (состояние потока)."""
        _fixed_clock(monkeypatch)
        buf = StringIO()
        stream = TimestampedStream(buf)
        assert stream._line_start is True
        stream.write("x")
        assert stream._line_start is False


class TestStampStdio:
    """stamp_stdio: метки в потоках своего процесса, повторный вызов безопасен."""

    def test_wraps_stdout_and_stderr(self, monkeypatch):
        monkeypatch.setattr(sys, "stdout", StringIO())
        monkeypatch.setattr(sys, "stderr", StringIO())
        stamp_stdio()
        assert isinstance(sys.stdout, TimestampedStream)
        assert isinstance(sys.stderr, TimestampedStream)

    def test_child_line_gets_stamp(self, monkeypatch):
        """Так консоль видит строку озвучки из `python -m lib.tts`."""
        _fixed_clock(monkeypatch)
        buf = StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        stamp_stdio()
        print("[TTS] Воспроизведение завершено")
        assert buf.getvalue() == "[13:46:07] [TTS] Воспроизведение завершено\n"

    def test_second_call_not_double_stamped(self, monkeypatch):
        """Уже завёрнутый поток не получает метку дважды."""
        _fixed_clock(monkeypatch)
        buf = StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        stamp_stdio()
        stamp_stdio()
        print("раз")
        assert buf.getvalue() == "[13:46:07] раз\n"

    def test_default_streams_left_alone(self, monkeypatch):
        """Без вызова sys.stdout — как был (import lib ничего не подменяет)."""
        buf = StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        assert not isinstance(sys.stdout, TimestampedStream)
