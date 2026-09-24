"""Тесты для lib/cdp_client.py (CDP-примитивы: HTTP, вкладки, JS)."""

import json
from unittest.mock import MagicMock, patch

from lib import cdp_client as cdc


class TestHttp:
    """Тесты для HTTP-хелпера."""

    def test_http_get(self, mocker):
        """GET запрашивает json версию."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"browser": "brave"}'
        mock_urlopen = mocker.patch("lib.cdp_client.urllib.request.urlopen")
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        result = cdc._http_request("http://localhost:9222/json/version")
        assert result == {"browser": "brave"}

    def test_http_post_sends_json(self, mocker):
        """POST отправляет JSON-тело."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_urlopen = mocker.patch("lib.cdp_client.urllib.request.urlopen")
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        cdc._http_request("http://x", {"a": 1})
        req = mock_urlopen.call_args[0][0]
        assert req.method == "POST"
        assert json.loads(req.data) == {"a": 1}


class TestTabs:
    """Тесты для работы со вкладками."""

    def test_list_tabs(self, mocker):
        """_list_tabs возвращает список вкладок."""
        mocker.patch(
            "lib.cdp_client._http_request",
            return_value=[{"id": "1", "url": "https://youtube.com"}],
        )
        tabs = cdc._list_tabs()
        assert len(tabs) == 1
        assert tabs[0]["id"] == "1"

    def test_find_tab(self, mocker):
        """find_tab находит вкладку по подстроке url."""
        mocker.patch(
            "lib.cdp_client._list_tabs",
            return_value=[
                {"url": "https://youtube.com/watch?v=abc"},
                {"url": "https://google.com"},
            ],
        )
        tab = cdc.find_tab("youtube")
        assert tab["url"].startswith("https://youtube.com")
        assert cdc.find_tab("нет такого") is None


class TestNewTabAndClose:
    """Тесты для open_new_tab и close_tab."""

    def test_open_new_tab_uses_put(self, mocker):
        """open_new_tab всегда создаёт вкладку через PUT /json/new."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = (
            b'{"id": "9", "url": "https://youtube.com/watch?v=x"}')
        mock_urlopen = mocker.patch("lib.cdp_client.urllib.request.urlopen")
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        tab = cdc.open_new_tab("https://youtube.com/watch?v=x")
        assert tab["id"] == "9"
        req = mock_urlopen.call_args[0][0]
        assert req.method == "PUT"
        assert "json/new" in req.full_url

    def test_open_new_tab_error_returns_none(self, mocker):
        """open_new_tab возвращает None при ошибке."""
        mocker.patch("lib.cdp_client.urllib.request.urlopen",
                     side_effect=Exception("boom"))
        assert cdc.open_new_tab("https://youtube.com") is None

    def test_close_tab_ok(self, mocker):
        """close_tab дергает /json/close/{id} и возвращает True."""
        mock_urlopen = mocker.patch("lib.cdp_client.urllib.request.urlopen")
        mock_urlopen.return_value.__enter__.return_value = MagicMock()
        assert cdc.close_tab({"id": "9"}) is True
        url = mock_urlopen.call_args[0][0]
        assert "json/close/9" in url

    def test_close_tab_error_returns_false(self, mocker):
        """close_tab возвращает False при ошибке."""
        mocker.patch("lib.cdp_client.urllib.request.urlopen",
                     side_effect=Exception("boom"))
        assert cdc.close_tab({"id": "9"}) is False


class TestIsRunning:
    """Тесты для is_running."""

    def test_is_running_true(self, mocker):
        """is_running возвращает True при успешном /json/version."""
        mocker.patch("lib.cdp_client._http_request", return_value={})
        assert cdc.is_running() is True

    def test_is_running_false(self, mocker):
        """is_running возвращает False при исключении."""
        mocker.patch("lib.cdp_client._http_request", side_effect=Exception("no"))
        assert cdc.is_running() is False


class TestEvalJs:
    """Тесты для eval_js."""

    def test_eval_js_success(self):
        """eval_js возвращает значение из Runtime.evaluate."""
        mock_ws = MagicMock()
        mock_ws.recv.return_value = json.dumps(
            {"id": 1, "result": {"result": {"type": "string", "value": "Hello"}}}
        )
        tab = {"webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/1"}
        with patch.object(cdc.websocket, "create_connection", return_value=mock_ws):
            ok, value = cdc.eval_js(tab, "1+1")
        assert ok is True
        assert value == "Hello"

    def test_eval_js_exception(self):
        """eval_js возвращает ошибку при исключении в браузере."""
        mock_ws = MagicMock()
        details = {"exceptionDetails": {"text": "boom"}}
        mock_ws.recv.return_value = json.dumps({"id": 1, "result": details})
        tab = {"webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/1"}
        with patch.object(cdc.websocket, "create_connection", return_value=mock_ws):
            ok, value = cdc.eval_js(tab, "x")
        assert ok is False


class TestClick:
    """Тесты для click."""

    def test_click_found(self, mocker):
        """click вызывает JS и кликает элемент."""
        mocker.patch("lib.cdp_client.eval_js", return_value=(True, "__CLICKED__"))
        ok, value = cdc.click({}, "button")
        assert ok is True

    def test_click_not_found(self, mocker):
        """click вернёт False, если элемента нет."""
        mocker.patch("lib.cdp_client.eval_js", return_value=(True, "__NOT_FOUND__"))
        ok, _ = cdc.click({}, "button")
        assert ok is False


class TestWaitSelector:
    """Тесты для wait_for_selector."""

    def test_wait_for_selector_found(self, mocker):
        """wait_for_selector возвращает True, если элемент найден."""
        mocker.patch("lib.cdp_client.eval_js", return_value=(True, True))
        assert cdc.wait_for_selector({}, "button") is True

    def test_wait_for_selector_timeout(self, mocker):
        """wait_for_selector возвращает False по таймауту."""
        mocker.patch("lib.cdp_client.eval_js", return_value=(True, False))
        assert cdc.wait_for_selector({}, "button", timeout=0.1) is False
