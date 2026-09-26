"""Встроенные проверки статусов (proxy, media, browser)."""


def _check_proxy(config=None) -> bool:
    """True, если прокси достижим (TCP connect к host:port).

    По умолчанию 192.168.1.107:1080. config — dict из status.json
    (секция checker_config): host/port/timeout.
    """
    host = "192.168.1.107"
    port = 1080
    timeout = 3.0
    if isinstance(config, dict):
        host = config.get("host", host)
        port = int(config.get("port", port))
        timeout = float(config.get("timeout", timeout))
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _check_media() -> bool:
    """Возвращает True, если в системе сейчас играет медиа."""
    from lib.runtime.media import is_media_playing
    try:
        return bool(is_media_playing())
    except Exception:
        return False


def _check_media_session() -> bool:
    """Возвращает True, если есть хоть одна медиа-сессия (хоть на паузе)."""
    from lib.runtime.media import is_media_available
    try:
        return bool(is_media_available())
    except Exception:
        return False


def _check_browser() -> bool:
    """Возвращает True, если браузер отвечает по CDP (порт 9222)."""
    from lib.browser.cdp_client import is_running
    try:
        return bool(is_running())
    except Exception:
        return False


def _check_browser_youtube() -> bool:
    """Возвращает True, если в браузере есть вкладка ютуба."""
    from lib.browser.cdp_client import find_tab, is_running
    try:
        if not is_running():
            return False
        return find_tab("youtube") is not None
    except Exception:
        return False
