"""Тесты main: кодировка Vosk и загрузка моделей."""


import sys
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock
import pytest
import lib.vosk_model as vm
from lib.transcription_worker import _fix_encoding
from lib.vosk_model import ensure_vosk_model


class TestEncodingFix:
    """Исправление кодировки Vosk на Windows."""

    def test_fix_encoding_identity_on_non_windows(self, monkeypatch):
        """На не-Windows возвращает текст как есть."""
        monkeypatch.setattr(sys, "platform", "linux")
        assert _fix_encoding("привет") == "привет"
        assert _fix_encoding("") == ""
        assert _fix_encoding("  ") == "  "

    def test_fix_encoding_cp866_to_utf8_on_windows(self, monkeypatch):
        """На Windows пытается cp866 -> utf-8."""
        monkeypatch.setattr(sys, "platform", "win32")
        result = _fix_encoding("привет")
        assert isinstance(result, str)

    def test_fix_encoding_keeps_valid_cyrillic(self, monkeypatch):
        """Корректная кириллица не перекодируется повторно (регрессия)."""
        monkeypatch.setattr(sys, "platform", "win32")
        mojibake = bytes([0xAF, 0xE0, 0xA8, 0xA2, 0xA5, 0xE2]).decode("cp866", errors="ignore")
        result = _fix_encoding(mojibake)
        assert "привет" in result or result == "привет"

    def test_fix_encoding_empty_string(self):
        """Пустая строка возвращается как есть."""
        assert _fix_encoding("") == ""

    def test_fix_encoding_normal_text(self):
        """Обычный текст возвращается как есть."""
        assert _fix_encoding("test") == "test"


class TestEnsureVoskModel:
    """Проверка и скачивание моделей Vosk."""

    def test_model_already_present(self, monkeypatch, tmp_path):
        """Готовая модель возвращается без скачивания."""
        model_dir = tmp_path / "vosk-model-small-ru-0.22"
        (model_dir / "am").mkdir(parents=True)
        (model_dir / "am" / "final.mdl").write_text("")
        monkeypatch.setattr(vm, "MODELS_DIR", str(tmp_path))
        assert ensure_vosk_model("ru") == str(model_dir)

    def test_downloads_and_extracts_model(self, monkeypatch, tmp_path):
        """Модель скачивается и распаковывается."""
        monkeypatch.setattr(vm, "MODELS_DIR", str(tmp_path))
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("vosk-model-small-ru-0.22/am/final.mdl", "x")
        zip_bytes = buf.getvalue()
        zip_path = str(tmp_path / "vosk-model-small-ru-0.22.zip")

        def fake_get(url, **kwargs):
            Path(zip_path).write_bytes(zip_bytes)
            resp = MagicMock()
            resp.__enter__.return_value = resp
            resp.iter_content.return_value = [zip_bytes]
            return resp

        monkeypatch.setattr(vm.requests, "get", fake_get)
        result = ensure_vosk_model("ru")
        assert "vosk-model-small-ru-0.22" in result

    def test_download_failure_raises_runtime_error(self, monkeypatch, tmp_path):
        """Ошибка загрузки вызывает RuntimeError."""
        monkeypatch.setattr(vm, "MODELS_DIR", str(tmp_path))

        def boom(*args, **kwargs):
            raise OSError("network down")

        monkeypatch.setattr(vm.requests, "get", boom)
        with pytest.raises(RuntimeError):
            ensure_vosk_model("ru")

    def test_unknown_language_raises_key_error(self, monkeypatch, tmp_path):
        """Неизвестный код языка даёт KeyError."""
        monkeypatch.setattr(vm, "MODELS_DIR", str(tmp_path))
        with pytest.raises(KeyError):
            ensure_vosk_model("xx")
