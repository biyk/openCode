"""Live-проверки YouTube для функциональных тестов.

Открывает тестовый ролик в НОВОЙ вкладке (не трогая существующие
вкладки ютуба), позволяет проверить состояние плеера (играет/пауза)
и корректно закрыть вкладку после теста.
"""

from typing import Optional

from lib.browser import cdp_client as cdc
from lib.browser import cdp_events as cde
from lib.browser.cdp_client import DEFAULT_PORT

# Потолок ожидания плеера — страховка от зависшей вкладки; штатно срабатывают
# события страницы (загрузка, изменение DOM), см. cdp_events.
PLAYER_TIMEOUT_S = 30.0

# Видео отдаёт метаданные: до этого состояние плеера нестабильно, и тест мог
# прочесть «паузу» там, где только что начался автоплей.
PLAYER_READY_JS = "document.querySelector('video').readyState >= 2"


def _player_state(tab: dict) -> str:
    """Состояние плеера: 'no-video' | 'playing' | 'paused'."""
    ok, value = cdc.eval_js(
        tab,
        "(function(){'use strict';"
        "var v = document.querySelector('video');"
        "if (!v) return 'no-video';"
        "return v.paused ? 'paused' : 'playing';"
        "})()",
    )
    if not ok:
        return "no-video"
    return value


def _tab_url(tab: dict) -> str:
    """Текущий URL конкретной вкладки (через location.href)."""
    ok, value = cdc.eval_js(tab, "location.href")
    return value if ok and isinstance(value, str) else ""


def youtube_open_test_video(url: str,
                            port: int = DEFAULT_PORT) -> Optional[dict]:
    """Открывает тестовый ролик в новой вкладке и ждёт плеер.

    Возвращает вкладку (обязательно закрыть через close_tab после теста)
    или None, если вкладку/плеер не удалось получить. Ждём события самой
    страницы: загрузку, появление `<video>` в DOM и метаданные ролика.
    Одиночная проба сразу после открытия вкладки была гонкой.
    """
    tab = cdc.open_new_tab(url, port)
    if not tab:
        print("[Browser] Не удалось открыть тестовый ролик")
        return None
    # Вкладку нужно сделать активной: OS-медиаклавиша (playpause)
    # адресуется активному табу, иначе пауза уйдёт на боевой ролик.
    cdc._activate(tab, port)
    cde.wait_page_loaded(tab, timeout=PLAYER_TIMEOUT_S)
    ready = (cde.wait_element(tab, "video", timeout=PLAYER_TIMEOUT_S)
             and "watch?v=" in _tab_url(tab))
    if not ready:
        print("[Browser] Плеер тестового ролика не загрузился "
              f"за {PLAYER_TIMEOUT_S:.0f} секунд")
        cdc.close_tab(tab, port)
        return None
    cde.wait_condition(tab, PLAYER_READY_JS, timeout=PLAYER_TIMEOUT_S)
    return tab


def youtube_video_playing(tab: dict) -> bool:
    """True, если видео на вкладке играет (автоплей нажал плей)."""
    return _player_state(tab) == "playing"


def youtube_video_paused(tab: dict) -> bool:
    """True, если видео на вкладке поставлено на паузу."""
    return _player_state(tab) == "paused"
