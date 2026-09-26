"""Live-проверки YouTube для функциональных тестов.

Открывает тестовый ролик в НОВОЙ вкладке (не трогая существующие
вкладки ютуба), позволяет проверить состояние плеера (играет/пауза)
и корректно закрыть вкладку после теста.
"""

import time
from typing import Optional

from lib.browser import cdp_client as cdc
from lib.browser.cdp_client import DEFAULT_PORT

# Таймаут ожидания появления плеера на тестовой вкладке (секунды).
PLAYER_TIMEOUT_S = 30.0

# Задержка перед опросом состояния плеера (видео грузится постепенно).
PLAYER_SETTLE_S = 3.0


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
    или None, если вкладку/плеер не удалось получить. Плеер ждём
    циклом до таймаута: <video> появляется в DOM не сразу, а после
    ускорения CDP (127.0.0.1 вместо localhost) одиночная проба
    сразу после открытия вкладки стала гонкой.
    """
    tab = cdc.open_new_tab(url, port)
    if not tab:
        print("[Browser] Не удалось открыть тестовый ролик")
        return None
    # Вкладку нужно сделать активной: OS-медиаклавиша (playpause)
    # адресуется активному табу, иначе пауза уйдёт на боевой ролик.
    cdc._activate(tab, port)
    state = "no-video"
    deadline = time.time() + PLAYER_TIMEOUT_S
    while time.time() < deadline:
        if "watch?v=" in _tab_url(tab):
            state = _player_state(tab)
            if state != "no-video":
                break
        time.sleep(1)
    if state == "no-video":
        print("[Browser] Плеер тестового ролика не загрузился "
              f"за {PLAYER_TIMEOUT_S:.0f} секунд")
        cdc.close_tab(tab, port)
        return None
    time.sleep(PLAYER_SETTLE_S)
    return tab


def youtube_video_playing(tab: dict) -> bool:
    """True, если видео на вкладке играет (автоплей нажал плей)."""
    return _player_state(tab) == "playing"


def youtube_video_paused(tab: dict) -> bool:
    """True, если видео на вкладке поставлено на паузу."""
    return _player_state(tab) == "paused"
