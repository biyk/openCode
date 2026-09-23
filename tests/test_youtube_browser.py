"""Тесты для lib/youtube_browser.py (сценарии YouTube)."""

from lib import youtube_browser as ytb


class TestYoutube:
    """Тесты для YouTube-сценариев."""

    def test_youtube_search(self, mocker):
        """youtube_search строит url с search_query."""
        mock_open = mocker.patch("lib.browser_control.open_url")
        ytb.youtube_search("музыка")
        url = mock_open.call_args[0][0]
        assert "youtube.com/results" in url
        assert "search_query=" in url
        import urllib.parse
        assert urllib.parse.unquote(url).find("музыка") >= 0

    def test_youtube_play(self, mocker):
        """youtube_play выполняет обе стадии."""
        tab = {"id": "1"}
        mocker.patch("lib.youtube_browser.youtube_search", return_value=tab)
        mocker.patch(
            "lib.youtube_browser.youtube_play_first_result", return_value=True
        )
        assert ytb.youtube_play("музыка") is True

    def test_youtube_play_no_tab(self, mocker):
        """youtube_play возвращает False без вкладки."""
        mocker.patch("lib.youtube_browser.youtube_search", return_value=None)
        assert ytb.youtube_play("музыка") is False

    def test_youtube_open_first_success(self, mocker):
        """youtube_open_first открывает первое видео, если вкладок ютуба нет."""
        tab = {"id": "1", "url": "https://www.youtube.com/"}
        mocker.patch("lib.browser_control.ensure_browser", return_value=True)
        mocker.patch("lib.cdp_client._list_tabs", return_value=[])
        mocker.patch("lib.browser_control.open_url", return_value=tab)
        mocker.patch("lib.cdp_client._activate")
        mocker.patch(
            "lib.youtube_browser._youtube_first_video_link",
            side_effect=["", "", "https://www.youtube.com/watch?v=abc"],
        )
        mocker.patch("lib.youtube_browser._YOUTUBE_FIRST_VIDEO_TIMEOUT", 30.0)
        mocker.patch("lib.youtube_browser._YOUTUBE_EXTENSIONS_SETTLE", 0.0)
        mocker.patch("lib.cdp_client.eval_js", return_value=(True, ""))
        assert ytb.youtube_open_first() is True

    def test_youtube_open_first_no_link(self, mocker):
        """youtube_open_first возвращает False без ссылки на видео."""
        tab = {"id": "1", "url": "https://www.youtube.com/"}
        mocker.patch("lib.browser_control.ensure_browser", return_value=True)
        mocker.patch("lib.cdp_client._list_tabs", return_value=[])
        mocker.patch("lib.browser_control.open_url", return_value=tab)
        mocker.patch("lib.cdp_client._activate")
        mocker.patch(
            "lib.youtube_browser._youtube_first_video_link", return_value=""
        )
        mocker.patch("lib.youtube_browser._YOUTUBE_FIRST_VIDEO_TIMEOUT", 0.1)
        mocker.patch("lib.cdp_client.eval_js", return_value=(True, ""))
        assert ytb.youtube_open_first() is False

    def test_youtube_open_first_no_tab(self, mocker):
        """youtube_open_first возвращает False без вкладки."""
        mocker.patch("lib.browser_control.ensure_browser", return_value=True)
        mocker.patch("lib.cdp_client._list_tabs", return_value=[])
        mocker.patch("lib.browser_control.open_url", return_value=None)
        assert ytb.youtube_open_first() is False

    def test_youtube_open_first_resumes_watch(self, mocker):
        """Если вкладка с роликом уже открыта — запускает текущее видео."""
        existing = {
            "id": "1",
            "type": "page",
            "url": "https://www.youtube.com/watch?v=abc",
        }
        mocker.patch("lib.browser_control.ensure_browser", return_value=True)
        mocker.patch("lib.cdp_client._list_tabs", return_value=[existing])
        mock_open = mocker.patch("lib.browser_control.open_url")
        mocker.patch("lib.cdp_client._activate")
        mocker.patch("lib.cdp_client.eval_js", return_value=(True, "playing"))
        assert ytb.youtube_open_first() is True
        mock_open.assert_not_called()

    def test_youtube_open_first_home_opens_first(self, mocker):
        """Главная ютуба уже открыта — открывает первое видео из ленты."""
        existing = {"id": "1", "type": "page", "url": "https://www.youtube.com/"}
        mocker.patch("lib.browser_control.ensure_browser", return_value=True)
        mocker.patch("lib.cdp_client._list_tabs", return_value=[existing])
        mock_open = mocker.patch("lib.browser_control.open_url")
        mocker.patch("lib.cdp_client._activate")
        mocker.patch(
            "lib.youtube_browser._youtube_first_video_link",
            return_value="https://www.youtube.com/watch?v=abc",
        )
        mocker.patch("lib.youtube_browser._YOUTUBE_EXTENSIONS_SETTLE", 0.0)
        mocker.patch("lib.cdp_client.eval_js", return_value=(True, ""))
        assert ytb.youtube_open_first() is True
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
            "lib.cdp_client._list_tabs",
            return_value=[worker, home, watch],
        )
        mock_open = mocker.patch("lib.browser_control.open_url")
        mock_wait = mocker.patch(
            "lib.youtube_browser._youtube_wait_and_open_first"
        )
        mock_resume = mocker.patch(
            "lib.youtube_browser._youtube_resume_current", return_value=True
        )
        assert ytb.youtube_open_first() is True
        mock_resume.assert_called_once_with(watch, 9222)
        mock_wait.assert_not_called()
        mock_open.assert_not_called()
