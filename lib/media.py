"""Определение состояния воспроизведения медиа (музыка/видео) на Windows."""

import subprocess
from pathlib import Path

_MEDIA_SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "media_state.ps1"


def _run_check(*extra_args: str) -> bool:
    """Запускает скрипт проверки и возвращает True при stdout 'true'.

    При любой ошибке (нет скрипта, таймаут, исключение) безопасно
    возвращает False.
    """
    if not _MEDIA_SCRIPT.exists():
        return False
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(_MEDIA_SCRIPT), *extra_args],
            capture_output=True, timeout=5)
        return result.stdout.decode("utf-8", errors="ignore").strip().lower() == "true"
    except Exception:
        return False


def is_media_playing() -> bool:
    """Возвращает True, если в системе сейчас проигрывается медиа.

    Использует Windows MediaTransportControls через PowerShell-скрипт.
    """
    return _run_check()


def is_media_available() -> bool:
    """Возвращает True, если есть хоть одна медиа-сессия (есть чем управлять).

    В отличие от is_media_playing(), True и на паузе/стопе — главное,
    что сессия существует. Нужно командам play/pause/stop.
    """
    return _run_check("-AnySession")
