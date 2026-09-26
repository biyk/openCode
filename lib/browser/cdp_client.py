"""CDP клиент: HTTP запросы, работа с вкладками, WebSocket соединение."""

import json
import time
import urllib.parse
import urllib.request
import websocket
from typing import Optional

DEFAULT_PORT = 9222
# Только IPv4: localhost сначала пробуется как ::1 — отказ ~2 с (tests/speed).
CDP_HOST = "127.0.0.1"


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
        return _http_request(f"http://{CDP_HOST}:{port}/json/list")
    except Exception as e:
        print(f"[Browser] Ошибка получения вкладок: {e}")
        return []


def is_running(port: int = DEFAULT_PORT) -> bool:
    """Проверяет, слушает ли браузер CDP порт."""
    try:
        _http_request(f"http://{CDP_HOST}:{port}/json/version")
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
        _http_request(f"http://{CDP_HOST}:{port}/json/activate/{tab.get('id')}")
        return True
    except Exception:
        return False


def open_new_tab(url: str, port: int = DEFAULT_PORT) -> Optional[dict]:
    """Создаёт НОВУЮ вкладку через /json/new (без переиспользования).

    В отличие от browser_control.open_url не проверяет существующие
    вкладки и не переключается на них — всегда открывает свежую.
    """
    try:
        q = urllib.parse.quote(url, safe="")
        req = urllib.request.Request(
            f"http://{CDP_HOST}:{port}/json/new?{q}", method="PUT")
        with urllib.request.urlopen(req, timeout=5) as resp:
            tab = json.loads(resp.read().decode("utf-8"))
        return tab
    except Exception as e:
        print(f"[Browser] Ошибка создания вкладки {url}: {e}")
        return None


def close_tab(tab: dict, port: int = DEFAULT_PORT) -> bool:
    """Закрывает вкладку через /json/close/{id}.

    CDP отвечает текстом («Target is closing»), а не JSON, поэтому
    используем сырой urlopen без разбора тела.
    """
    try:
        with urllib.request.urlopen(
                f"http://{CDP_HOST}:{port}/json/close/{tab.get('id')}",
                timeout=5):
            return True
    except Exception as e:
        print(f"[Browser] Ошибка закрытия вкладки: {e}")
        return False


def _ws_for(tab: dict) -> Optional[websocket.WebSocket]:
    """Открывает WebSocket к вкладке (localhost в URL меняем на IPv4)."""
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return None
    ws_url = ws_url.replace("//localhost:", f"//{CDP_HOST}:")
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


def eval_js(tab: dict, script: str) -> tuple[bool, str]:
    """Выполняет JavaScript на вкладке через Runtime.evaluate."""
    try:
        ws = _ws_for(tab)
        if not ws:
            return False, "нет webSocketDebuggerUrl"
        payload = {
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": script, "returnByValue": True},
        }
        ws.send(json.dumps(payload))
        for _ in range(20):
            data = json.loads(ws.recv())
            if data.get("id") != 1:
                continue
            result = data.get("result", {})
            if result.get("exceptionDetails"):
                ws.close()
                return False, str(result["exceptionDetails"])
            value = result.get("result", {}).get("value")
            ws.close()
            return True, value if value is not None else ""
        ws.close()
        return False, "нет ответа от Runtime.evaluate"
    except Exception as e:
        print(f"[Browser] Ошибка eval_js: {e}")
        return False, str(e)


def click(tab: dict, selector: str) -> tuple[bool, str]:
    """Кликает по первому элементу, подходящему под селектор."""
    script = (
        "(function(){"
        f"var el = document.querySelector('{selector}');"
        "if (!el) return '__NOT_FOUND__';"
        "el.click();"
        "return '__CLICKED__';"
        "})()"
    )
    ok, value = eval_js(tab, script)
    if not ok:
        return False, value
    if value == "__NOT_FOUND__":
        return False, f"элемент '{selector}' не найден"
    return True, value


def wait_for_selector(tab: dict, selector: str, timeout: float = 15.0) -> bool:
    """Ждёт появления элемента по селектору."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        ok, value = eval_js(tab, f"!!document.querySelector('{selector}')")
        if ok and value is True:
            return True
        time.sleep(0.5)
    return False
