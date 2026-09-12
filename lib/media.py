"""Определение состояния воспроизведения медиа (музыка/видео) на Windows."""

import subprocess
from pathlib import Path

_MEDIA_SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "media_state.ps1"


def is_media_playing() -> bool:
    """Возвращает True, если в системе сейчас проигрывается медиа.

    Использует Windows MediaTransportControls через PowerShell-скрипт.
    При любой ошибке (нет скрипта, таймаут, исключение) безопасно
    возвращает False — команды управления просто не рекомендуются.
    """
    if not _MEDIA_SCRIPT.exists():
        return False
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(_MEDIA_SCRIPT)],
            capture_output=True, timeout=5)
        return result.stdout.decode("utf-8", errors="ignore").strip().lower() == "true"
    except Exception:
        return False
