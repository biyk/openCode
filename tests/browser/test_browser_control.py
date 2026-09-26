"""Тесты для lib/browser_control.py (запуск браузера, вкладки, CLI)."""

from unittest.mock import MagicMock

from lib import browser_control as bc


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
        mocker.patch(
            "lib.browser_control._find_browser_exe", return_value="C:/brave.exe"
        )
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
