# TOOLTIP: Проба вкладок тестового браузера «жива ли и что играет» с коротким таймаутом
"""Опрос вкладок через CDP: «жива ли страница и что на ней играет».

Признака «эта вкладка издаёт звук» в CDP `/json/list` нет, поэтому каждую
обычную вкладку спрашиваем JS-пробой по `video`/`audio`. Проба идёт коротким
таймаутом (`CDP_PROBE_S`): вкладка с занятым главным потоком (браузерная игра,
тяжёлый редактор) на JS не ответит, а ждать её общим потолком — минуты
молчания микрофона: опрос синхронный и идёт внутри цикла распознавания.

«Не ответила» ≠ «не играет»: такие вкладки считаются отдельно (`Scan.dead`) и
озвучиваются отдельно, иначе зависший браузер выглядит тишиной, а команда —
промахом по пустому месту.

Плееры в iframe (встроенные ролики) пробой не видны: смотрим основной документ.
"""

from typing import NamedTuple, Optional

from lib.browser import cdp_client as cdc
from lib.browser.cdp_client import DEFAULT_PORT
from lib.core.tuning import CDP_PROBE_S

# Элемент «играет» = не на паузе, не закончен, данные текут (readyState ≥ 2).
PLAYING = "if (m.paused || m.ended || m.readyState < 2) continue;"
# Звук идёт именно с этой вкладки: не заглушена и громкость ненулевая.
AUDIBLE = "!m.muted && m.volume > 0"


def probe_js() -> str:
    """JS вопроса «звучит ли страница»: первый играющий элемент и его скорость."""
    return (
        "(function(){'use strict';"
        "var els = document.querySelectorAll('video, audio');"
        "for (var i = 0; i < els.length; i++) {"
        "  var m = els[i];"
        + PLAYING +
        "  return {playing: true, audible: " + AUDIBLE + ","
        "          rate: m.playbackRate};"
        "}"
        "return {playing: false, audible: false, rate: 0};"
        "})()"
    )


def page_tabs(port: int = DEFAULT_PORT) -> list[dict]:
    """Обычные вкладки: service worker и фоновые страницы расширений — мимо."""
    return [t for t in cdc._list_tabs(port)
            if t.get("type", "page") in ("page", "")]


def eval_tab(tab: dict, script: str,
             timeout: float = CDP_PROBE_S) -> dict:
    """JS на вкладке → словарь; пустой словарь — вкладка не ответила."""
    ok, value = cdc.eval_js(tab, script, timeout)
    if not ok:
        return {}
    return value if isinstance(value, dict) else {}


class Scan(NamedTuple):
    """Итог обхода вкладок: кому крутить звук, кого ещё слышно, кто молчит."""

    tab: Optional[dict]   # звучащая вкладка; None — не найдена
    info: dict            # её ответ пробы (playing/audible/rate)
    others: int           # играющие, но не выбранные (заглушённые)
    dead: int             # не ответившие за CDP_PROBE_S: тихо ли там — неизвестно


def sounding(tabs: list[dict]) -> Scan:
    """Ищет вкладку, где что-то играет; на звучащей обход прекращается.

    Обход прекращается на первой НЕзаглушённой играющей вкладке: дальше идти
    незачем, а каждая зависшая вкладка стоит `CDP_PROBE_S` секунд — без этого
    полный перебор глохил бы микрофон на минуту. Заглушённые помечаются в
    `others`: если звучащей так и нет, крутить придётся первую из них.
    """
    script = probe_js()
    muted: Optional[dict] = None   # первая играющая, но заглушённая
    info: dict = {}
    extra = 0                      # играющие, кроме первой заглушённой
    dead = 0
    for item in tabs:
        state = eval_tab(item, script)
        if not state:
            dead += 1
            continue
        if not state.get("playing"):
            continue
        if state.get("audible"):
            return Scan(item, state, extra + (1 if muted else 0), dead)
        if muted is None:
            muted, info = item, state
        else:
            extra += 1
    return Scan(muted, info, extra, dead)
