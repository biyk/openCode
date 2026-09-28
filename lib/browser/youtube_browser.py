"""Сценарии YouTube поверх CDP-браузера.

Все ожидания — событийные (`cdp_events`): дождаться загрузки страницы,
дождаться нужного элемента в DOM, проверить, что плеер заиграл. Фиксированных
`sleep` здесь нет: они либо мешают, либо не успевают за загрузкой.
"""

import urllib.parse
from typing import Optional

from lib.browser import cdp_client as cdc
from lib.browser import cdp_events as cde
from lib.browser.cdp_client import DEFAULT_PORT
from lib.core.tuning import CDP_ELEMENT_S, CDP_FIRST_TRY_S

_YOUTUBE_SELECTORS = {
    "player": "button.ytp-play-button",
    "result": "ytd-video-renderer a#video-title, ytd-video-renderer #video-title",
    "video": "video",
    "feed": 'ytd-rich-item-renderer a[href*="/watch?v="]',
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

_YOUTUBE_PLAYING_JS = "!document.querySelector('video').paused"


def _bc():
    """Ленивый доступ к browser_control (только open_url/ensure_browser)."""
    from lib import browser_control as bc
    return bc


def _youtube_first_video_link(tab: dict) -> str:
    """Первая ссылка на видео из ленты (реклама пропускается)."""
    ok, value = cdc.eval_js(tab, _YOUTUBE_FIRST_VIDEO_SCRIPT)
    if ok and isinstance(value, str):
        return value
    return ""


def _youtube_is_watch(url: str) -> bool:
    """True, если url — страница ролика (/watch или /shorts)."""
    path = urllib.parse.urlparse(url).path.lower()
    return "/watch" in path or path.startswith("/shorts")


def _wait_player_ready(tab: dict) -> bool:
    """Ждёт плеер по событиям: загрузка страницы, затем <video> в DOM.

    Две пробы: первая могла прийти на документ-заглушку навигации, где
    readyState уже complete, а ролика ещё нет.
    """
    for timeout in (CDP_FIRST_TRY_S, CDP_ELEMENT_S):
        cde.wait_page_loaded(tab)
        if cde.wait_element(tab, _YOUTUBE_SELECTORS["video"], timeout=timeout):
            return True
    print("[Browser] Плеер на странице не появился")
    return False


def _try_play(tab: dict) -> bool:
    """Запускает воспроизведение и ждёт подтверждения от страницы.

    Play() без жеста пользователя браузер может блокировать — тогда пробуем
    клик по кнопке плеера; и то и другое проверяем состоянием `paused`, а не
    верим ответу скрипта.
    """
    cdc.eval_js(tab, _YOUTUBE_RESUME_SCRIPT)
    if cde.wait_condition(tab, _YOUTUBE_PLAYING_JS, CDP_FIRST_TRY_S):
        return True
    cdc.click(tab, _YOUTUBE_SELECTORS["player"])
    return cde.wait_condition(tab, _YOUTUBE_PLAYING_JS, CDP_FIRST_TRY_S)


def _youtube_resume_current(tab: dict, port: int = DEFAULT_PORT) -> bool:
    """Переключается на вкладку и запускает уже открытое видео."""
    cdc._activate(tab, port)
    if not _wait_player_ready(tab):
        return False
    if _try_play(tab):
        print("[Browser] Запущено текущее видео")
        return True
    print("[Browser] Не удалось запустить текущее видео")
    return False


def _youtube_wait_and_open_first(tab: dict, port: int = DEFAULT_PORT) -> bool:
    """Ждёт ленту на вкладке и открывает первое не-рекламное видео."""
    cdc._activate(tab, port)
    cde.wait_page_loaded(tab)
    if not cde.wait_element(tab, _YOUTUBE_SELECTORS["feed"]):
        print("[Browser] Лента видео не загрузилась")
        return False
    link = _youtube_first_video_link(tab)
    if not link:
        print("[Browser] Не удалось найти ссылку на первое видео")
        return False
    if not cde.navigate(tab, link):
        print("[Browser] Не удалось открыть первое видео")
        return False
    print(f"[Browser] Открыто первое видео: {link}")
    if _wait_player_ready(tab) and _try_play(tab):
        print("[Browser] Запущено текущее видео")
    return True


def _youtube_page_tabs(port: int = DEFAULT_PORT) -> list:
    """Обычные (не service worker) вкладки youtube.com."""
    found = []
    for tab in cdc._list_tabs(port):
        if tab.get("type", "page") not in ("page", ""):
            continue
        if cdc._hostname(tab.get("url", "")) == "youtube.com":
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
        cde.wait_page_loaded(tab)
        cde.wait_element(tab, _YOUTUBE_SELECTORS["result"])
    return tab


def youtube_play_first_result(tab: dict, port: int = DEFAULT_PORT) -> bool:
    """Кликает первый результат поиска и жмёт плей."""
    cdc._activate(tab, port)
    if not cde.wait_element(tab, _YOUTUBE_SELECTORS["result"]):
        print("[Browser] Результаты поиска не загрузились")
        return False
    ok, value = cdc.click(tab, _YOUTUBE_SELECTORS["result"])
    if not ok:
        print(f"[Browser] Не удалось выбрать ролик: {value}")
        return False
    return _wait_player_ready(tab) and _try_play(tab)


def youtube_play(query: str, port: int = DEFAULT_PORT) -> bool:
    """Полный сценарий: открыть ютуб, найти ролик, запустить."""
    tab = youtube_search(query, port)
    if not tab:
        print("[Browser] Не удалось открыть ютуб")
        return False
    return youtube_play_first_result(tab, port)


def youtube_open_first(port: int = DEFAULT_PORT) -> bool:
    """Нет вкладки ютуба — открыть главную и первое видео.
    Есть вкладка с роликом — запустить его. Иначе — первое из ленты."""
    bc = _bc()
    if not bc.ensure_browser(port):
        print("[Browser] Не удалось открыть ютуб")
        return False
    pages = _youtube_page_tabs(port)
    watch = next((t for t in pages if _youtube_is_watch(t.get("url", ""))),
                 None)
    if watch:
        return _youtube_resume_current(watch, port)
    if pages:
        return _youtube_wait_and_open_first(pages[0], port)
    tab = bc.open_url("https://youtube.com", port)
    if not tab:
        print("[Browser] Не удалось открыть ютуб")
        return False
    return _youtube_wait_and_open_first(tab, port)
