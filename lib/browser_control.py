"""Управление браузером через CDP (remote debugging).

Модуль позволяет открывать вкладки и выполнять JavaScript на любой
вкладке без лишних слоёв: только HTTP + WebSocket CDP. Если сайт уже
открыт во вкладке — open-url переключается на неё, а не создаёт новую.

Использование из команд:
    python -m lib.browser_control status
    python -m lib.browser_control tabs
    python -m lib.browser_control open-url "https://youtube.com"
    python -m lib.browser_control eval "https://youtube.com" "document.title"
    python -m lib.browser_control click "https://youtube.com" "button.ytp-play-button"
    python -m lib.browser_control youtube-play "музыка для кодинга"
    python -m lib.browser_control youtube-first
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import websocket
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    try:
        os.system("chcp 65001 >nul")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

DEFAULT_PORT = 9222

_COMMON_WINDOWS_PATHS = [
    Path(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
    Path(r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe"),
]

_YOUTUBE_SELECTORS = {
    "player": "button.ytp-play-button",
    "result": "ytd-video-renderer a#video-title, ytd-video-renderer #video-title",
}

_YOUTUBE_FIRST_VIDEO_SCRIPT = (
    "(function(){"
    "var items = document.querySelectorAll('ytd-rich-item-renderer');"
    "for (var i = 0; i < items.length; i++) {"
    "  if (items[i].querySelector('ytd-ad-slot-renderer')) continue;"
    "  var a = items[i].querySelector('a[href*=\"/watch?v=\"]');"
    "  if (a && a.href) return a.href;"
    "}"
    "return '';"
    "})()"
)


def _http_request(url: str, data: Optional[dict] = None) -> dict:
    """GET (data=None) или POST (data=json) к CDP-эндпоинту."""
    req = urllib.request.Request(url)
    if data is not None:
        req = urllib.request.Request(
            url, data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _list_tabs(port: int = DEFAULT_PORT) -> list:
    """Возвращает список вкладок через /json/list."""
    try:
        return _http_request(f"http://localhost:{port}/json/list")
    except Exception as e:
        print(f"[Browser] Ошибка получения вкладок: {e}")
        return []


def is_running(port: int = DEFAULT_PORT) -> bool:
    """Проверяет, слушает ли браузер debug-порт."""
    try:
        _http_request(f"http://localhost:{port}/json/version")
        return True
    except Exception:
        return False


def _find_browser_exe() -> Optional[str]:
    """Ищет исполняемый файл Brave."""
    found = shutil.which("brave-browser") or shutil.which("brave")
    if found:
        return found
    for path in _COMMON_WINDOWS_PATHS:
        if path.exists():
            return str(path)
    return None


def _profile_dir(port: int = DEFAULT_PORT) -> Path:
    """Каталог профиля браузера внутри репозитория."""
    root = Path(__file__).resolve().parent.parent
    return root / f".voice-cdp-profile-{port}"


def ensure_browser(port: int = DEFAULT_PORT) -> bool:
    """Проверяет/запускает браузер с remote-debugging-port."""
    if is_running(port):
        print(f"[Browser] Уже запущен на порту {port}")
        return True

    exe = _find_browser_exe()
    if not exe:
        print("[Browser] Brave не найден")
        return False

    profile = _profile_dir(port)
    profile.mkdir(exist_ok=True)
    print(f"[Browser] Запуск {exe} с debug-портом {port}")
    subprocess.Popen(
        [
            exe,
            f"--remote-debugging-port={port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        time.sleep(1)
        if is_running(port):
            print("[Browser] Браузер готов")
            return True
    print("[Browser] Браузер не ответил за 30 секунд")
    return False


def _hostname(url: str) -> str:
    """Хост из url без www и в нижнем регистре, '' если определить не удалось."""
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
        if _hostname(tab.get("url", "")) == target:
            return tab
    return None


def open_url(url: str, port: int = DEFAULT_PORT) -> Optional[dict]:
    """Открывает url в новой вкладке; если вкладка с тем же сайтом уже
    открыта — переключается на неё вместо создания новой."""
    if not ensure_browser(port):
        return None
    existing = _tab_for_site(_list_tabs(port), url)
    if existing:
        _activate(existing, port)
        print(f"[Browser] Переключено на открытую вкладку: {existing.get('url')}")
        return existing
    try:
        q = urllib.parse.quote(url, safe="")
        req = urllib.request.Request(
            f"http://localhost:{port}/json/new?{q}", method="PUT"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            tab = json.loads(resp.read().decode("utf-8"))
        print(f"[Browser] Открыта вкладка: {url}")
        return tab
    except Exception as e:
        print(f"[Browser] Ошибка открытия вкладки {url}: {e}")
        return None


def find_tab(url_part: str, port: int = DEFAULT_PORT) -> Optional[dict]:
    """Ищет вкладку, url которой содержит подстроку."""
    for tab in _list_tabs(port):
        if url_part.lower() in tab.get("url", "").lower():
            return tab
    return None


def _ws_for(tab: dict) -> Optional[websocket.WebSocket]:
    """Открывает WebSocket к вкладке."""
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
            if data.get("id") == 1:
                result = data.get("result", {})
                if result.get("exceptionDetails"):
                    w = ws
                    w.close()
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
        f"(function(){{"
        f"var el = document.querySelector('{selector}');"
        f"if (!el) return '__NOT_FOUND__';"
        f"el.click();"
        f"return '__CLICKED__';"
        f"}})()"
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


def _activate(tab: dict, port: int = DEFAULT_PORT) -> bool:
    """Переключает фокус на вкладку."""
    try:
        _http_request(f"http://localhost:{port}/json/activate/{tab.get('id')}")
        return True
    except Exception:
        return False


def youtube_search(query: str, port: int = DEFAULT_PORT) -> Optional[dict]:
    """Открывает ютуб с поисковым запросом, возвращает вкладку."""
    tab = open_url(
        "https://www.youtube.com/results?search_query="
        + urllib.parse.quote(query, safe=""),
        port=port,
    )
    if tab:
        time.sleep(3)
    return tab


def youtube_play_first_result(tab: dict, port: int = DEFAULT_PORT) -> bool:
    """Кликает первый результат поиска и жмёт плей."""
    _activate(tab, port)
    wait_for_selector(tab, _YOUTUBE_SELECTORS["result"])
    ok, value = click(tab, _YOUTUBE_SELECTORS["result"])
    if not ok:
        print(f"[Browser] Не удалось выбрать ролик: {value}")
        return False
    time.sleep(5)
    click(tab, _YOUTUBE_SELECTORS["player"])
    return True


def youtube_play(query: str, port: int = DEFAULT_PORT) -> bool:
    """Полный сценарий: открыть ютуб, найти ролик, запустить."""
    tab = youtube_search(query, port)
    if not tab:
        print("[Browser] Не удалось открыть ютуб")
        return False
    return youtube_play_first_result(tab, port)


_YOUTUBE_FIRST_VIDEO_TIMEOUT = 30.0
_YOUTUBE_EXTENSIONS_SETTLE = 3.0


def _youtube_first_video_link(tab: dict) -> str:
    """Первая ссылка на видео из ленты (рекламные элементы пропускаются)."""
    ok, value = eval_js(tab, _YOUTUBE_FIRST_VIDEO_SCRIPT)
    if ok and isinstance(value, str):
        return value
    return ""


def youtube_open_first(port: int = DEFAULT_PORT) -> bool:
    """Открывает главную ютуба, ждёт загрузку ленты и расширений,
    затем открывает первое видео."""
    tab = open_url("https://youtube.com", port)
    if not tab:
        print("[Browser] Не удалось открыть ютуб")
        return False
    _activate(tab, port)
    deadline = time.time() + _YOUTUBE_FIRST_VIDEO_TIMEOUT
    link = ""
    while time.time() < deadline:
        link = _youtube_first_video_link(tab)
        if link:
            break
        time.sleep(1)
    if not link:
        print("[Browser] Список видео не загрузился за "
              f"{_YOUTUBE_FIRST_VIDEO_TIMEOUT:.0f} секунд")
        return False
    time.sleep(_YOUTUBE_EXTENSIONS_SETTLE)
    ok, _ = eval_js(tab, f"window.location.href = {json.dumps(link)}")
    if not ok:
        print("[Browser] Не удалось открыть первое видео")
        return False
    print(f"[Browser] Открыто первое видео: {link}")
    return True


def _cmd_status(port: int) -> int:
    if is_running(port):
        print(f"[Browser] Браузер работает на порту {port}")
        return 0
    print(f"[Browser] Браузер НЕ работает на порту {port}")
    return 1


def _cmd_tabs(port: int) -> int:
    tabs = _list_tabs(port)
    for t in tabs:
        print(f"{t.get('id', '?')}  {t.get('title', '')}  {t.get('url', '')}")
    return 0


def _cmd_open_url(url: str, port: int) -> int:
    tab = open_url(url, port)
    return 0 if tab else 1


def _cmd_eval(url_part: str, script: str, port: int) -> int:
    tab = wait_for_tab(url_part, port)
    if not tab:
        print(f"[Browser] Вкладка с '{url_part}' не найдена")
        return 1
    ok, value = eval_js(tab, script)
    print(value)
    return 0 if ok else 1


def _cmd_click(url_part: str, selector: str, port: int) -> int:
    tab = wait_for_tab(url_part, port)
    if not tab:
        print(f"[Browser] Вкладка с '{url_part}' не найдена")
        return 1
    ok, value = click(tab, selector)
    if not ok:
        print(f"[Browser] Клик не удался: {value}")
        return 1
    print(value)
    return 0


def _cmd_youtube_play(query: str, port: int) -> int:
    if youtube_play(query, port):
        print(f"[Browser] Плей запущен: {query}")
        return 0
    print(f"[Browser] Сценарий ютуба не выполнен: {query}")
    return 1


def main(argv: Optional[list] = None) -> int:
    """Точка входа CLI."""
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    port = DEFAULT_PORT
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
        argv = [a for i, a in enumerate(argv) if not (argv[i - 1] == "--port")]
    args = [a for a in argv[1:] if a != "--port"]

    if cmd == "status":
        return _cmd_status(port)
    if cmd == "tabs":
        return _cmd_tabs(port)
    if cmd == "open-url":
        return _cmd_open_url(args[0], port)
    if cmd == "eval":
        return _cmd_eval(args[0], " ".join(args[1:]), port)
    if cmd == "click":
        return _cmd_click(args[0], args[1], port)
    if cmd == "youtube-play":
        return _cmd_youtube_play(" ".join(args), port)
    if cmd == "youtube-first":
        if youtube_open_first(port):
            return 0
        return 1
    print(f"[Browser] Неизвестная команда: {cmd}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
