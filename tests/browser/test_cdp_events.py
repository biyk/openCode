# TOOLTIP: Тесты событийных ожиданий CDP: загрузка страницы, элемент, переход
"""Тесты lib/browser/cdp_events.py.

Вместо живого браузера — WS-заглушка: она отдаёт заготовленные сообщения
(либо имитирует таймаут чтения) и сама отвечает на Runtime.evaluate.
"""

import json

import websocket

from lib.browser import cdp_events as ce


class FakeWs:
    """WebSocket к вкладке: сообщения по порядку, None — таймаут чтения."""

    def __init__(self, messages=(), js_value=None):
        self.messages = list(messages)
        self.js_value = js_value
        self.sent = []
        self.closed = False

    def send(self, payload):
        msg = json.loads(payload)
        self.sent.append(msg)
        if self.js_value is not None and msg.get("method") == "Runtime.evaluate":
            self.messages.append({"id": msg["id"],
                                  "result": {"result": {"value": self.js_value}}})

    def recv(self):
        if not self.messages:
            raise websocket.WebSocketException("сокет пуст")
        reply = self.messages.pop(0)
        if reply is None:
            raise websocket.WebSocketException("таймаут чтения")
        return json.dumps(reply)

    def settimeout(self, timeout):
        """Шаг ожидания заглушке не нужен: сообщения отдаются сразу."""

    def close(self):
        self.closed = True


def _attach(mocker, ws):
    """Вешает заглушку на открытие соединений; возвращает её."""
    mocker.patch.object(ce.cdc, "_ws_for", return_value=ws)
    return ws


TAB = {"id": "1", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/1"}


class TestWaitPageLoaded:
    """Ожидание события загрузки страницы."""

    def test_load_event_ends_wait(self, mocker):
        ws = _attach(mocker, FakeWs([{"method": "Page.loadEventFired"}]))
        assert ce.wait_page_loaded(TAB) is True
        assert ws.sent[0]["method"] == "Page.enable"
        assert ws.closed is True

    def test_ready_state_covers_missed_event(self, mocker):
        """Событие можно пропустить (документ загрузился до подписки)."""
        ws = _attach(mocker, FakeWs([None], js_value="complete"))
        assert ce.wait_page_loaded(TAB) is True
        assert ws.sent[-1]["params"]["expression"] == "document.readyState"

    def test_still_loading_until_deadline(self, mocker):
        _attach(mocker, FakeWs([None], js_value="loading"))
        assert ce.wait_page_loaded(TAB, timeout=0.05) is False

    def test_no_socket(self, mocker):
        _attach(mocker, None)
        assert ce.wait_page_loaded(TAB) is False


class TestNavigate:
    """Переход по url с ожиданием загрузки новой страницы."""

    def test_navigates_and_waits_load(self, mocker):
        ws = _attach(mocker, FakeWs([
            {"id": 2, "result": {}},
            {"method": "Page.domContentEventFired"},
        ]))
        assert ce.navigate(TAB, "https://youtube.com/watch?v=1") is True
        nav = ws.sent[1]
        assert nav["method"] == "Page.navigate"
        assert nav["params"]["url"].endswith("watch?v=1")

    def test_browser_refused_url(self, mocker):
        _attach(mocker, FakeWs([{"id": 2, "result": {"errorText": "ERR"}}]))
        assert ce.navigate(TAB, "https://youtube.com", timeout=0.05) is False


class TestWaitCondition:
    """JS-условие внутри страницы (MutationObserver + редкая перепроверка)."""

    def test_condition_true(self, mocker):
        ws = _attach(mocker, FakeWs(js_value=True))
        assert ce.wait_condition(TAB, "document.querySelector('video')") is True
        params = ws.sent[0]["params"]
        assert params["awaitPromise"] is True
        assert "MutationObserver" in params["expression"]

    def test_condition_resolved_false(self, mocker):
        """Страница сама сказала «не дождались» — не ждём второй заход."""
        _attach(mocker, FakeWs(js_value=False))
        assert ce.wait_condition(TAB, "x", timeout=0.05) is False

    def test_js_exception_is_failure(self, mocker):
        _attach(mocker, FakeWs([
            {"id": 1, "result": {"exceptionDetails": {"text": "boom"}}}]))
        assert ce.wait_condition(TAB, "x", timeout=0.05) is False

    def test_silence_ends_wait(self, mocker):
        _attach(mocker, FakeWs([]))
        assert ce.wait_condition(TAB, "x", timeout=0.05) is False

    def test_missing_context_is_retried(self, mocker):
        """«Нет контекста исполнения» — страница перезапустилась: ждём дальше."""
        _attach(mocker, FakeWs(
            [{"id": 1, "error": {"code": -32000,
                                 "message": "Cannot find default execution"}}],
            js_value=True))
        assert ce.wait_condition(TAB, "x", timeout=5) is True

    def test_condition_js_is_one_promise_expression(self):
        """Регресс: «new Promise(...)(...)» браузер ронял в TypeError
        «(intermediate value) is not a function» — вызова в конце быть не должно.
        """
        js = ce._condition_js("document.querySelector('video')", 5)
        assert js.startswith("new Promise(")
        assert js.rstrip().endswith("})")
        assert ">=10" in js          # 5 секунд / шаг 0.5 — столько перепроверок

    def test_wait_element_builds_selector_check(self, mocker):
        ws = _attach(mocker, FakeWs(js_value=True))
        assert ce.wait_element(TAB, "video", timeout=0.05) is True
        assert "document.querySelector" in ws.sent[0]["params"]["expression"]
        assert '"video"' in ws.sent[0]["params"]["expression"]

    def test_socket_error_is_failure(self, mocker):
        """Сбой соединения — False, а не исключение в голосовой цикл."""
        mocker.patch.object(ce.cdc, "_ws_for",
                            side_effect=OSError("браузер закрылся"))
        assert ce.wait_page_loaded(TAB) is False
        assert ce.wait_condition(TAB, "x") is False
        assert ce.navigate(TAB, "https://youtube.com") is False
