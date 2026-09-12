"""Тесты определения статуса проигрывания медиа."""

import subprocess

from lib import media
from lib.media import is_media_playing


class TestMedia:
    """Тесты для is_media_playing."""

    def test_returns_true_when_playing(self, mocker):
        """stdout 'true' → играет музыка."""
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"true\r\n")
        mocker.patch("lib.media.subprocess.run", return_value=proc)
        assert is_media_playing() is True

    def test_returns_false_when_not_playing(self, mocker):
        """stdout 'false' → музыки нет."""
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"false")
        mocker.patch("lib.media.subprocess.run", return_value=proc)
        assert is_media_playing() is False

    def test_returns_false_on_exception(self, mocker):
        """Исключение при запуске PowerShell → False."""
        mocker.patch("lib.media.subprocess.run", side_effect=OSError("no powershell"))
        assert is_media_playing() is False

    def test_returns_false_when_script_missing(self, monkeypatch):
        """Скрипт не существует → False, subprocess не вызывается."""
        monkeypatch.setattr(media, "_MEDIA_SCRIPT", media.Path("nonexistent.ps1"))
        assert is_media_playing() is False
