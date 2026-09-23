"""Сценарии YouTube поверх CDP-браузера."""

import json
import time
import urllib.parse
from typing import Optional

from lib.cdp_client import DEFAULT_PORT

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

_YOUTUBE_RESUME_SCRIPT = (
    "(function(){"
    "var v = document.querySelector('video');"
    "if (!v) return 'no-video';"
    "var p = v.play();"
    "if (p && p.catch) p.catch(function(){});"
    "return 'playing';"
    "})()"
)

_YOUTUBE_FIRST_VIDEO_TIMEOUT = 30.0
_YOUTUBE_EXTENSIONS_SETTLE = 3.0


def _bc():
    from lib import browser_control as bc
    return bc


def _youtube_first_video_link(tab: dict) -> str:
    """Первая ссылка на видео из ленты (реклама пропускается)."""
    ok, value = _bc().eval_js(tab, _YOUTUBE_FIRST_VIDEO_SCRIPT)
    if ok and isinstance(value, str):
        return value
    return ""


def _youtube_is_watch(url: str) -> bool:
    """True, если url — страница ролика (/watch или /shorts)."""
    path = urllib.parse.urlparse(url).path.lower()
    return "/watch" in path or path.startswith("/shorts")


def _youtube_resume_current(tab: dict, port: int = DEFAULT_PORT) -> bool:
    """Переключается на вкладку и запускает уже открытое видео."""
    bc = _bc()
    bc._activate(tab, port)
    ok, value = bc.eval_js(tab, _YOUTUBE_RESUME_SCRIPT)
    if ok and value == "playing":
        print("[Browser] Запущено текущее видео")
        return True
    clicked, _ = bc.click(tab, _YOUTUBE_SELECTORS["player"])
    if clicked:
        print("[Browser] Запущено текущее видео")
        return True
    print("[Browser] Не удалось запустить текущее видео")
    return False


def _youtube_wait_and_open_first(tab: dict, port: int = DEFAULT_PORT) -> bool:
    """Ждёт ленту на вкладке и открывает первое не-рекламное видео."""
    bc = _bc()
    bc._activate(tab, port)
    deadline = time.time() + bc._YOUTUBE_FIRST_VIDEO_TIMEOUT
    link = ""
    while time.time() < deadline:
        link = bc._youtube_first_video_link(tab)
        if link:
            break
        time.sleep(1)
    if not link:
        print("[Browser] Список видео не загрузился за "
              f"{bc._YOUTUBE_FIRST_VIDEO_TIMEOUT:.0f} секунд")
        return False
    time.sleep(bc._YOUTUBE_EXTENSIONS_SETTLE)
    ok, _ = bc.eval_js(tab, f"window.location.href = {json.dumps(link)}")
    if not ok:
        print("[Browser] Не удалось открыть первое видео")
        return False
    print(f"[Browser] Открыто первое видео: {link}")
    return True


def _youtube_page_tabs(port: int = DEFAULT_PORT) -> list:
    """Обычные (не service worker) вкладки youtube.com."""
    bc = _bc()
    found = []
    for tab in bc._list_tabs(port):
        if tab.get("type", "page") not in ("page", ""):
            continue
        if bc._hostname(tab.get("url", "")) == "youtube.com":
            found.append(tab)
    return found


def youtube_search(query: str, port: int = DEFAULT_PORT) -> Optional[dict]:
    """Открывает ютуб с поисковым запросом, возвращает вкладку."""
    tab = _bc().open_url(
        "https://www.youtube.com/results?search_query="
        + urllib.parse.quote(query, safe=""),
        port=port,
    )
    if tab:
        time.sleep(3)
    return tab


def youtube_play_first_result(tab: dict, port: int = DEFAULT_PORT) -> bool:
    """Кликает первый результат поиска и жмёт плей."""
    bc = _bc()
    bc._activate(tab, port)
    bc.wait_for_selector(tab, _YOUTUBE_SELECTORS["result"])
    ok, value = bc.click(tab, _YOUTUBE_SELECTORS["result"])
    if not ok:
        print(f"[Browser] Не удалось выбрать ролик: {value}")
        return False
    time.sleep(5)
    bc.click(tab, _YOUTUBE_SELECTORS["player"])
    return True


def youtube_play(query: str, port: int = DEFAULT_PORT) -> bool:
    """Полный сценарий: открыть ютуб, найти ролик, запустить."""
    bc = _bc()
    tab = bc.youtube_search(query, port)
    if not tab:
        print("[Browser] Не удалось открыть ютуб")
        return False
    return bc.youtube_play_first_result(tab, port)


def youtube_open_first(port: int = DEFAULT_PORT) -> bool:
    """Нет вкладки ютуба — открыть главную и первое видео.
    Есть вкладка с роликом — запустить его. Иначе — первое из ленты."""
    bc = _bc()
    if not bc.ensure_browser(port):
        print("[Browser] Не удалось открыть ютуб")
        return False
    pages = bc._youtube_page_tabs(port)
    watch = next((t for t in pages if bc._youtube_is_watch(t.get("url", ""))),
                 None)
    if watch:
        return bc._youtube_resume_current(watch, port)
    if pages:
        return bc._youtube_wait_and_open_first(pages[0], port)
    tab = bc.open_url("https://youtube.com", port)
    if not tab:
        print("[Browser] Не удалось открыть ютуб")
        return False
    return bc._youtube_wait_and_open_first(tab, port)
