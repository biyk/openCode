"""CDP клиент: HTTP запросы, работа с вкладками, WebSocket соединение."""

import json
import time
import urllib.parse
import urllib.request
import websocket
from typing import Optional

DEFAULT_PORT = 9222


def _http_request(url: str, data: Optional[dict] = None) -> dict:
    """Выполняет GET (data=None) или POST (data=json) запрос к CDP эндпоинту."""
    req = urllib.request.Request(url)
    if data is not None:
        req = urllib.request.Request(
            url, data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _list_tabs(port: int = DEFAULT_PORT) -> list:
    """Возвращает список вкладок через CDP /json/list."""
    try:
        return _http_request(f"http://localhost:{port}/json/list")
    except Exception as e:
        print(f"[Browser] Ошибка получения вкладок: {e}")
        return []


def is_running(port: int = DEFAULT_PORT) -> bool:
    """Проверяет, слушает ли браузер CDP порт."""
    try:
        _http_request(f"http://localhost:{port}/json/version")
        return True
    except Exception:
        return False


def _hostname(url: str) -> str:
    """Извлекает хост из URL без www и в нижнем регистре."""
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return ""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _tab_for_site(tabs: list, url: str) -> Optional[dict]:
    """Возвращает открытую вкладку с тем же сайтом (без учёта www)."""
    target = _hostname(url)
    if not target:
        return None
    for tab in tabs:
        if tab.get("type", "page") not in ("page", ""):
            continue
        if _hostname(tab.get("url", "")) == target:
            return tab
    return None


def find_tab(url_part: str, port: int = DEFAULT_PORT) -> Optional[dict]:
    """Ищет вкладку, url которой содержит подстроку."""
    for tab in _list_tabs(port):
        if url_part.lower() in tab.get("url", "").lower():
            return tab
    return None


def _activate(tab: dict, port: int = DEFAULT_PORT) -> bool:
    """Переключает фокус на вкладку через CDP."""
    try:
        _http_request(f"http://localhost:{port}/json/activate/{tab.get('id')}")
        return True
    except Exception:
        return False


def _ws_for(tab: dict) -> Optional[websocket.WebSocket]:
    """Открывает WebSocket соединение к вкладке."""
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return None
    return websocket.create_connection(ws_url, timeout=30)


def wait_for_tab(url_part: str, port: int = DEFAULT_PORT, timeout: float = 15.0) -> Optional[dict]:
    """Ждёт появления вкладки с нужным url."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        tab = find_tab(url_part, port)
        if tab:
            return tab
        time.sleep(0.5)
    return None
