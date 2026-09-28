# TOOLTIP: Ожидания вкладки CDP по событиям: загрузка страницы, элемент, переход
"""Событийное ожидание состояния вкладки вместо пауз по таймеру.

* `wait_page_loaded` / `navigate` — событие `Page.loadEventFired` (и ответ
  `Page.navigate`); документ мог загрузиться до подписки — тогда признаком
  служит readyState;
* `wait_condition` / `wait_element` — JS-условие на Promise внутри страницы:
  срабатывает в момент изменения DOM, а не по нашему опросу.

Дедлайн (CDP_PAGE_LOAD_S / CDP_ELEMENT_S) — страховка от зависшей вкладки.
Предыстория и порядок шагов «открой ютуб» — AGENTS.md.
"""

import json
import time
from typing import Any, Optional

import websocket

from lib.browser import cdp_client as cdc
from lib.core.errors import swallowed
from lib.core.tuning import CDP_ELEMENT_S, CDP_PAGE_LOAD_S

# После этих событий страницу считаем загруженной.
LOAD_EVENTS = ("Page.loadEventFired", "Page.domContentEventFired")
_PROBE_GAP = 0.5        # шаг: переспросить readyState / повторить запрос
_RECHECK_S = 0.5        # редкая перепроверка условия внутри страницы
_READY_JS = {"expression": "document.readyState", "returnByValue": True}


def _open(tab: dict) -> Any:
    """WebSocket к вкладке; None, если адреса нет или браузер лег."""
    try:
        return cdc._ws_for(tab)
    except Exception as error:
        return swallowed("cdp.ws_open", error, None)


def _close(ws: Any) -> None:
    """Закрываем соединение; его сбой на результат ожидания не влияет."""
    try:
        ws.close()
    except Exception as error:
        swallowed("cdp.ws_close", error)


def _send(ws: Any, mid: int, method: str,
          params: Optional[dict] = None) -> None:
    """Один CDP-вызов с id (ответы и события различаем по id/method)."""
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))


def _recv(ws: Any, wait: float) -> Optional[dict]:
    """Одно сообщение WS либо None, если за `wait` секунд ничего не пришло.

    Пауза чтения — штатная ветка (так устроено ожидание события), не логируем.
    """
    ws.settimeout(max(0.05, wait))
    try:
        return json.loads(ws.recv())
    except (websocket.WebSocketException, OSError, ValueError):
        return None


def _answer(ws: Any, mid: int, deadline: float) -> Optional[dict]:
    """Ответ на запрос `mid`, события по пути пропускаются.

    None — до дедлайна ответа не было: страница молчит или соединение умерло.
    """
    while time.time() < deadline:
        msg = _recv(ws, deadline - time.time())
        if msg is None:
            return None
        if msg.get("id") == mid:
            return msg
    return None


def _value(msg: dict) -> Any:
    """Значение из ответа Runtime.evaluate (returnByValue)."""
    return ((msg.get("result") or {}).get("result") or {}).get("value")


def _wait_load_event(ws: Any, deadline: float) -> bool:
    """Ждёт событие загрузки, по пути переспрашивая document.readyState.

    Документ мог загрузиться раньше подписки — тогда признак это
    readyState == interactive/complete.
    """
    probe: Optional[int] = None
    mid = 10
    while time.time() < deadline:
        msg = _recv(ws, _PROBE_GAP)
        if msg is None:
            if probe is None:         # предыдущий ответ ещё забран
                _send(ws, mid, "Runtime.evaluate", _READY_JS)
                probe, mid = mid, mid + 1
            continue
        if msg.get("method") in LOAD_EVENTS:
            return True
        if probe is not None and msg.get("id") == probe:
            probe = None
            if _value(msg) in ("interactive", "complete"):
                return True
    return False


def wait_page_loaded(tab: dict, timeout: float = CDP_PAGE_LOAD_S) -> bool:
    """True, когда страница догружена (событие браузера, не наша пауза)."""
    ws = _open(tab)
    if ws is None:
        return False
    try:
        _send(ws, 1, "Page.enable")
        return _wait_load_event(ws, time.time() + timeout)
    except Exception as error:
        return swallowed("cdp.wait_page_loaded", error, False)
    finally:
        _close(ws)


def navigate(tab: dict, url: str, timeout: float = CDP_PAGE_LOAD_S) -> bool:
    """Переход по url: ответ навигации, затем событие загрузки новой страницы."""
    ws = _open(tab)
    if ws is None:
        return False
    try:
        _send(ws, 1, "Page.enable")
        _send(ws, 2, "Page.navigate", {"url": url})
        ack = _answer(ws, 2, time.time() + timeout) or {}
        refused = ack.get("error") or (ack.get("result") or {}).get("errorText")
        if not ack or refused:
            return False              # браузер не смог пойти по url
        return _wait_load_event(ws, time.time() + timeout)
    except Exception as error:
        return swallowed("cdp.navigate", error, False)
    finally:
        _close(ws)


def _condition_js(script: str, timeout: float) -> str:
    """JS-Promise: условие проверяется на каждое изменение DOM.

    setInterval перепроверяет редко: video.paused в DOM не отражён.
    """
    checks = max(1, int(timeout / _RECHECK_S))
    return (
        "new Promise(function(resolve){"
        "function ok(){try{return Boolean(" + script + ");}"
        "catch(e){return false;}}"
        "if(ok()){resolve(true);return;}"
        "var mo=new MutationObserver(function(){"
        "if(ok()){mo.disconnect();resolve(true);}});"
        "mo.observe(document,{childList:true,subtree:true,attributes:true});"
        "var n=0;"
        "var t=setInterval(function(){"
        "if(ok()){clearInterval(t);mo.disconnect();resolve(true);}"
        "else if(++n>=" + str(checks) + "){clearInterval(t);mo.disconnect();"
        "resolve(false);}}," + str(int(_RECHECK_S * 1000)) + ");})"
    )


def wait_condition(tab: dict, script: str,
                   timeout: float = CDP_ELEMENT_S) -> bool:
    """True, когда JS-условие внутри страницы стало истинным.

    «Нет контекста исполнения» — не провал, а след перезапуска документа:
    запрос повторяем до истечения срока.
    """
    ws = _open(tab)
    if ws is None:
        return False
    params = {"expression": _condition_js(script, timeout),
              "awaitPromise": True, "returnByValue": True}
    try:
        deadline = time.time() + timeout + 2
        while time.time() < deadline:
            _send(ws, 1, "Runtime.evaluate", params)
            msg = _answer(ws, 1, deadline)
            if msg is None:
                return False
            if msg.get("error"):
                time.sleep(_PROBE_GAP)
                continue
            if (msg.get("result") or {}).get("exceptionDetails"):
                print(f"[Browser] Ошибка ожидания условия: {script}")
                return False
            return bool(_value(msg))
        return False
    except Exception as error:
        return swallowed("cdp.wait_condition", error, False)
    finally:
        _close(ws)


def wait_element(tab: dict, selector: str,
                 timeout: float = CDP_ELEMENT_S) -> bool:
    """Ждёт появления элемента: событие DOM внутри страницы, не наш опрос."""
    js = f"document.querySelector({json.dumps(selector)})"
    return wait_condition(tab, js, timeout)
