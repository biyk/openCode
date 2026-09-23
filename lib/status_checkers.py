"""Встроенные проверки статусов (vpn, media, browser)."""


def _check_vpn() -> bool:
    """Возвращает True, если youtube доступен напрямую (VPN включён).

    Прокси-признак: без VPN youtube в РФ недоступен (таймаут/сброс),
    с VPN отвечает 200. Сам VPN скрипт не включает — только проверяет.
    """
    try:
        import urllib.request
        request = urllib.request.Request(
            "https://www.youtube.com/", method="HEAD",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(request, timeout=4) as response:
            return response.status == 200
    except Exception:
        return False


def _check_media() -> bool:
    """Возвращает True, если в системе сейчас играет медиа."""
    from lib.media import is_media_playing
    try:
        return bool(is_media_playing())
    except Exception:
        return False


def _check_media_session() -> bool:
    """Возвращает True, если есть хоть одна медиа-сессия (хоть на паузе)."""
    from lib.media import is_media_available
    try:
        return bool(is_media_available())
    except Exception:
        return False


def _check_browser() -> bool:
    """Возвращает True, если браузер отвечает по CDP (порт 9222)."""
    from lib.cdp_client import is_running
    try:
        return bool(is_running())
    except Exception:
        return False


def _check_browser_youtube() -> bool:
    """Возвращает True, если в браузере есть вкладка ютуба."""
    from lib.cdp_client import find_tab, is_running
    try:
        if not is_running():
            return False
        return find_tab("youtube") is not None
    except Exception:
        return False
