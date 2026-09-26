"""Тесты для lib/browser/youtube_live.py (состояние плеера, открытие/закрытие)."""

from lib.browser import youtube_live as yl


class TestPlayerState:
    """Определение состояния плеера по eval_js."""

    def test_playing(self, mocker):
        mocker.patch("lib.browser.cdp_client.eval_js", return_value=(True, "playing"))
        assert yl._player_state({"id": "1"}) == "playing"
        assert yl.youtube_video_playing({"id": "1"}) is True

    def test_paused(self, mocker):
        mocker.patch("lib.browser.cdp_client.eval_js", return_value=(True, "paused"))
        assert yl._player_state({"id": "1"}) == "paused"
        assert yl.youtube_video_paused({"id": "1"}) is True

    def test_no_video(self, mocker):
        mocker.patch("lib.browser.cdp_client.eval_js", return_value=(True, "no-video"))
        assert yl._player_state({"id": "1"}) == "no-video"
        assert yl.youtube_video_playing({"id": "1"}) is False
        assert yl.youtube_video_paused({"id": "1"}) is False

    def test_eval_error_is_no_video(self, mocker):
        mocker.patch("lib.browser.cdp_client.eval_js", return_value=(False, "err"))
        assert yl._player_state({"id": "1"}) == "no-video"


class TestOpenTestVideo:
    """Открытие тестового ролика в новой вкладке."""

    def test_open_success(self, mocker):
        mocker.patch("lib.browser.cdp_client.open_new_tab", return_value={"id": "7"})
        mocker.patch.object(
            yl, "_tab_url", return_value="https://youtube.com/watch?v=x")
        mocker.patch("lib.browser.cdp_client.eval_js", return_value=(True, "playing"))
        mocker.patch.object(yl, "PLAYER_SETTLE_S", 0.0)
        tab = yl.youtube_open_test_video("https://youtube.com/watch?v=x")
        assert tab == {"id": "7"}

    def test_open_no_tab(self, mocker):
        mocker.patch("lib.browser.cdp_client.open_new_tab", return_value=None)
        assert yl.youtube_open_test_video("https://youtube.com") is None

    def test_open_no_player_closes_tab(self, mocker):
        mocker.patch("lib.browser.cdp_client.open_new_tab", return_value={"id": "7"})
        mocker.patch.object(yl, "_tab_url", return_value="")
        mocker.patch("lib.browser.cdp_client.eval_js", return_value=(True, "no-video"))
        mock_close = mocker.patch("lib.browser.cdp_client.close_tab")
        mocker.patch.object(yl, "PLAYER_TIMEOUT_S", 0.1)
        assert yl.youtube_open_test_video("https://youtube.com") is None
        mock_close.assert_called_once()
