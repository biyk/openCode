"""Тесты для lib/browser_control.py (управление браузером через CDP)."""

import json
from unittest.mock import MagicMock, patch

from lib import browser_control as bc


class TestHttp:
    """Тесты для HTTP-хелпера."""

    def test_http_get(self, mocker):
        """GET запрашивает json версию."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"browser": "brave"}'
        mock_urlopen = mocker.patch("lib.browser_control.urllib.request.urlopen")
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        result = bc._http_request("http://localhost:9222/json/version")
        assert result == {"browser": "brave"}

    def test_http_post_sends_json(self, mocker):
        """POST отправляет JSON-тело."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_urlopen = mocker.patch("lib.browser_control.urllib.request.urlopen")
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        bc._http_request("http://x", {"a": 1})
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
        tabs = bc._list_tabs()
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
        tab = bc.find_tab("youtube")
        assert tab["url"].startswith("https://youtube.com")
        assert bc.find_tab("нет такого") is None


class TestIsRunning:
    """Тесты для is_running."""

    def test_is_running_true(self, mocker):
        """is_running возвращает True при успешном /json/version."""
        mocker.patch("lib.cdp_client._http_request", return_value={})
        assert bc.is_running() is True

    def test_is_running_false(self, mocker):
        """is_running возвращает False при исключении."""
        mocker.patch("lib.cdp_client._http_request", side_effect=Exception("no"))
        assert bc.is_running() is False


class TestEnsureBrowser:
    """Тесты для ensure_browser."""

    def test_already_running(self, mocker):
        """Если браузер уже запущен — новые процессы не стартуют."""
        mocker.patch("lib.browser_control.is_running", return_value=True)
        mock_popen = mocker.patch("lib.browser_control.subprocess.Popen")
        bc.ensure_browser()
        mock_popen.assert_not_called()

    def test_start_and_wait(self, mocker):
        """Запускает браузер с debug-портом и ждёт готовности."""
        ready = {"value": 0}

        def _fake_is_running(port=None):
            return ready["value"] == 1

        mocker.patch("lib.browser_control.is_running", side_effect=_fake_is_running)
        mocker.patch("lib.browser_control._find_browser_exe", return_value="C:/brave.exe")
        mock_popen = mocker.patch("lib.browser_control.subprocess.Popen")

        def _make_ready(*args, **kwargs):
            ready["value"] = 1

        mock_popen.side_effect = _make_ready
        bc.ensure_browser()
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "--remote-debugging-port=9222" in args

    def test_no_browser(self, mocker):
        """Без найденного браузера — неуспех."""
        mocker.patch("lib.browser_control.is_running", return_value=False)
        mocker.patch("lib.browser_control._find_browser_exe", return_value=None)
        assert bc.ensure_browser() is False


class TestOpenUrl:
    """Тесты для open_url."""

    def test_open_url_called(self, mocker):
        """open_url открывает новую вкладку через PUT, если нет открытой."""
        mocker.patch("lib.browser_control.ensure_browser", return_value=True)
        mocker.patch("lib.browser_control._list_tabs", return_value=[])
        mocker.patch("lib.browser_control._activate")
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"id": "2", "url": "https://youtube.com"}'
        mock_urlopen = mocker.patch("lib.browser_control.urllib.request.urlopen")
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        tab = bc.open_url("https://youtube.com")
        assert tab["url"] == "https://youtube.com"
        req = mock_urlopen.call_args[0][0]
        assert req.method == "PUT"
        assert "json/new" in req.full_url

    def test_open_url_switches_to_existing(self, mocker):
        """Если вкладка с тем же сайтом уже открыта — переключается не её."""
        existing = {"id": "1", "url": "https://www.youtube.com/watch?v=abc"}
        mocker.patch("lib.browser_control.ensure_browser", return_value=True)
        mocker.patch("lib.browser_control._list_tabs", return_value=[existing])
        mock_activate = mocker.patch("lib.browser_control._activate")
        mock_urlopen = mocker.patch("lib.browser_control.urllib.request.urlopen")
        tab = bc.open_url("https://youtube.com")
        assert tab is existing
        mock_activate.assert_called_once_with(existing, 9222)
        mock_urlopen.assert_not_called()

    def test_open_url_browser_fail(self, mocker):
        """Если браузер не запустился — вкладка не открывается."""
        mocker.patch("lib.browser_control.ensure_browser", return_value=False)
        assert bc.open_url("https://youtube.com") is None


class TestEvalJs:
    """Тесты для eval_js."""

    def test_eval_js_success(self):
        """eval_js возвращает значение из Runtime.evaluate."""
        mock_ws = MagicMock()
        mock_ws.recv.return_value = json.dumps(
            {"id": 1, "result": {"result": {"type": "string", "value": "Hello"}}}
        )
        tab = {"webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/1"}
        with patch.object(bc.websocket, "create_connection", return_value=mock_ws):
            ok, value = bc.eval_js(tab, "1+1")
        assert ok is True
        assert value == "Hello"

    def test_eval_js_exception(self):
        """eval_js возвращает ошибку при исключении в браузере."""
        mock_ws = MagicMock()
        details = {"exceptionDetails": {"text": "boom"}}
        mock_ws.recv.return_value = json.dumps({"id": 1, "result": details})
        tab = {"webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/1"}
        with patch.object(bc.websocket, "create_connection", return_value=mock_ws):
            ok, value = bc.eval_js(tab, "x")
        assert ok is False


class TestClick:
    """Тесты для click."""

    def test_click_found(self, mocker):
        """click вызывает JS и кликает элемент."""
        mocker.patch("lib.browser_control.eval_js", return_value=(True, "__CLICKED__"))
        ok, value = bc.click({}, "button")
        assert ok is True

    def test_click_not_found(self, mocker):
        """click вернёт False, если элемента нет."""
        mocker.patch("lib.browser_control.eval_js", return_value=(True, "__NOT_FOUND__"))
        ok, _ = bc.click({}, "button")
        assert ok is False


class TestYoutube:
    """Тесты для YouTube-сценариев."""

    def test_youtube_search(self, mocker):
        """youtube_search строит url с search_query."""
        mock_open = mocker.patch("lib.browser_control.open_url")
        bc.youtube_search("музыка")
        url = mock_open.call_args[0][0]
        assert "youtube.com/results" in url
        assert "search_query=" in url
        import urllib.parse
        assert urllib.parse.unquote(url).find("музыка") >= 0

    def test_youtube_play(self, mocker):
        """youtube_play выполняет обе стадии."""
        tab = {"id": "1"}
        mocker.patch("lib.browser_control.youtube_search", return_value=tab)
        mocker.patch("lib.browser_control.youtube_play_first_result", return_value=True)
        assert bc.youtube_play("музыка") is True

    def test_youtube_play_no_tab(self, mocker):
        """youtube_play возвращает False без вкладки."""
        mocker.patch("lib.browser_control.youtube_search", return_value=None)
        assert bc.youtube_play("музыка") is False

    def test_youtube_open_first_success(self, mocker):
        """youtube_open_first открывает первое видео, если вкладок ютуба нет."""
        tab = {"id": "1", "url": "https://www.youtube.com/"}
        mocker.patch("lib.browser_control.ensure_browser", return_value=True)
        mocker.patch("lib.browser_control._list_tabs", return_value=[])
        mocker.patch("lib.browser_control.open_url", return_value=tab)
        mocker.patch("lib.browser_control._activate")
        mocker.patch("lib.browser_control._youtube_first_video_link",
                     side_effect=["", "", "https://www.youtube.com/watch?v=abc"])
        mocker.patch("lib.browser_control._YOUTUBE_FIRST_VIDEO_TIMEOUT", 30.0)
        mocker.patch("lib.browser_control._YOUTUBE_EXTENSIONS_SETTLE", 0.0)
        mocker.patch("lib.browser_control.eval_js", return_value=(True, ""))
        assert bc.youtube_open_first() is True

    def test_youtube_open_first_no_link(self, mocker):
        """youtube_open_first возвращает False без ссылки на видео."""
        tab = {"id": "1", "url": "https://www.youtube.com/"}
        mocker.patch("lib.browser_control.ensure_browser", return_value=True)
        mocker.patch("lib.browser_control._list_tabs", return_value=[])
        mocker.patch("lib.browser_control.open_url", return_value=tab)
        mocker.patch("lib.browser_control._activate")
        mocker.patch("lib.browser_control._youtube_first_video_link",
                     return_value="")
        mocker.patch("lib.browser_control._YOUTUBE_FIRST_VIDEO_TIMEOUT", 0.1)
        mocker.patch("lib.browser_control.eval_js", return_value=(True, ""))
        assert bc.youtube_open_first() is False

    def test_youtube_open_first_no_tab(self, mocker):
        """youtube_open_first возвращает False без вкладки."""
        mocker.patch("lib.browser_control.ensure_browser", return_value=True)
        mocker.patch("lib.browser_control._list_tabs", return_value=[])
        mocker.patch("lib.browser_control.open_url", return_value=None)
        assert bc.youtube_open_first() is False

    def test_youtube_open_first_resumes_watch(self, mocker):
        """Если вкладка с роликом уже открыта — запускает текущее видео."""
        existing = {
            "id": "1",
            "type": "page",
            "url": "https://www.youtube.com/watch?v=abc",
        }
        mocker.patch("lib.browser_control.ensure_browser", return_value=True)
        mocker.patch("lib.browser_control._list_tabs", return_value=[existing])
        mock_open = mocker.patch("lib.browser_control.open_url")
        mocker.patch("lib.browser_control._activate")
        mocker.patch("lib.browser_control.eval_js", return_value=(True, "playing"))
        assert bc.youtube_open_first() is True
        mock_open.assert_not_called()

    def test_youtube_open_first_home_opens_first(self, mocker):
        """Главная ютуба уже открыта — открывает первое видео из ленты."""
        existing = {"id": "1", "type": "page", "url": "https://www.youtube.com/"}
        mocker.patch("lib.browser_control.ensure_browser", return_value=True)
        mocker.patch("lib.browser_control._list_tabs", return_value=[existing])
        mock_open = mocker.patch("lib.browser_control.open_url")
        mocker.patch("lib.browser_control._activate")
        mocker.patch(
            "lib.browser_control._youtube_first_video_link",
            return_value="https://www.youtube.com/watch?v=abc",
        )
        mocker.patch("lib.browser_control._YOUTUBE_EXTENSIONS_SETTLE", 0.0)
        mocker.patch("lib.browser_control.eval_js", return_value=(True, ""))
        assert bc.youtube_open_first() is True
        mock_open.assert_not_called()

    def test_youtube_open_first_prefers_watch_over_home(self, mocker):
        """При главной и ролике — запускает ролик, не трогая ленту."""
        home = {"id": "1", "type": "page", "url": "https://www.youtube.com/"}
        watch = {
            "id": "2",
            "type": "page",
            "url": "https://www.youtube.com/watch?v=abc",
        }
        worker = {
            "id": "3",
            "type": "service_worker",
            "url": "https://www.youtube.com/sw.js",
        }
        mocker.patch("lib.browser_control.ensure_browser", return_value=True)
        mocker.patch(
            "lib.browser_control._list_tabs",
            return_value=[worker, home, watch],
        )
        mock_open = mocker.patch("lib.browser_control.open_url")
        mock_wait = mocker.patch("lib.browser_control._youtube_wait_and_open_first")
        mock_resume = mocker.patch(
            "lib.browser_control._youtube_resume_current", return_value=True
        )
        assert bc.youtube_open_first() is True
        mock_resume.assert_called_once_with(watch, 9222)
        mock_wait.assert_not_called()
        mock_open.assert_not_called()


class TestWaitSelector:
    """Тесты для wait_for_selector."""

    def test_wait_for_selector_found(self, mocker):
        """wait_for_selector возвращает True, если элемент найден."""
        mocker.patch("lib.browser_control.eval_js", return_value=(True, True))
        assert bc.wait_for_selector({}, "button") is True

    def test_wait_for_selector_timeout(self, mocker):
        """wait_for_selector возвращает False по таймауту."""
        mocker.patch("lib.browser_control.eval_js", return_value=(True, False))
        assert bc.wait_for_selector({}, "button", timeout=0.1) is False


class TestMain:
    """Тесты для CLI-точки входа."""

    def test_main_unknown(self, capsys):
        """Неизвестная команда печатает ошибку."""
        assert bc.main(["bogus"]) == 1

    def test_main_status_ok(self, mocker, capsys):
        """status возвращает 0 при работающем браузере."""
        mocker.patch("lib.browser_control.is_running", return_value=True)
        assert bc.main(["status"]) == 0

    def test_main_open_url(self, mocker):
        """open-url возвращает 0 при успехе."""
        mocker.patch("lib.browser_control.open_url", return_value={"id": "1"})
        assert bc.main(["open-url", "https://youtube.com"]) == 0

    def test_main_eval(self, mocker):
        """eval печатает результат js."""
        mocker.patch("lib.browser_control.wait_for_tab", return_value={"id": "1"})
        mocker.patch("lib.browser_control.eval_js", return_value=(True, "result"))
        assert bc.main(["eval", "youtube", "document.title"]) == 0

    def test_main_click(self, mocker):
        """click возвращает 0 при клике."""
        mocker.patch("lib.browser_control.wait_for_tab", return_value={"id": "1"})
        mocker.patch("lib.browser_control.click", return_value=(True, "__CLICKED__"))
        assert bc.main(["click", "youtube", "button"]) == 0

    def test_main_youtube_play(self, mocker):
        """youtube-play возвращает 0 при успехе."""
        mocker.patch("lib.browser_control.youtube_play", return_value=True)
        assert bc.main(["youtube-play", "музыка"]) == 0
