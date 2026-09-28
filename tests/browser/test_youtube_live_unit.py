# TOOLTIP: Юнит-тесты live-хелперов YouTube: состояние плеера, открытие вкладки
"""Тесты для lib/browser/youtube_live.py (состояние плеера, открытие/закрытие).

Событийные ожидания (`cdp_events`) заглушены: здесь проверяется порядок шагов
сценария и закрытие вкладки при неуспехе.
"""

import pytest

from lib.browser import youtube_live as yl


@pytest.fixture(autouse=True)
def events(mocker):
    """Ожидания загрузки/элемента/условия по умолчанию успешны."""
    return mocker.patch.multiple(
        yl.cde, wait_page_loaded=mocker.DEFAULT, wait_element=mocker.DEFAULT,
        wait_condition=mocker.DEFAULT)


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

    url = "https://youtube.com/watch?v=x"

    def _tab(self, mocker):
        return mocker.patch("lib.browser.cdp_client.open_new_tab",
                            return_value={"id": "7"})

    def test_open_success(self, mocker, events):
        """Вкладка открыта, ролик на месте — ждём метаданные и отдаём вкладку."""
        self._tab(mocker)
        mocker.patch.object(yl, "_tab_url", return_value=self.url)
        assert yl.youtube_open_test_video(self.url) == {"id": "7"}
        assert events["wait_element"].call_args[0][1] == "video"
        events["wait_condition"].assert_called_once()

    def test_open_no_tab(self, mocker):
        """Вкладку не получили — ничего не ждём."""
        mocker.patch("lib.browser.cdp_client.open_new_tab", return_value=None)
        assert yl.youtube_open_test_video(self.url) is None

    def test_open_no_player_closes_tab(self, mocker, events):
        """Плеер так и не появился — тестовую вкладку закрываем."""
        self._tab(mocker)
        events["wait_element"].return_value = False
        mock_close = mocker.patch("lib.browser.cdp_client.close_tab")
        assert yl.youtube_open_test_video(self.url) is None
        mock_close.assert_called_once()

    def test_open_redirected_closes_tab(self, mocker, events):
        """Видео есть, но страницу перекинуло с ролика — это не тестовый ролик."""
        self._tab(mocker)
        mocker.patch.object(yl, "_tab_url", return_value="https://youtube.com/")
        mock_close = mocker.patch("lib.browser.cdp_client.close_tab")
        assert yl.youtube_open_test_video(self.url) is None
        mock_close.assert_called_once()
        events["wait_condition"].assert_not_called()

    def test_open_waits_player_by_event(self, mocker, events):
        """Регресс гонки: появление <video> ждём событием, а не одиночной пробой."""
        self._tab(mocker)
        mocker.patch.object(yl, "_tab_url", return_value=self.url)
        assert yl.youtube_open_test_video(self.url) == {"id": "7"}
        assert events["wait_page_loaded"].called
        assert events["wait_condition"].call_args[0][1] == yl.PLAYER_READY_JS

    def test_open_activates_tab(self, mocker, events):
        """Вкладка делается активной: медиаклавиша адресуется активным табу."""
        self._tab(mocker)
        mocker.patch.object(yl, "_tab_url", return_value=self.url)
        mock_activate = mocker.patch("lib.browser.cdp_client._activate")
        yl.youtube_open_test_video(self.url)
        mock_activate.assert_called_once_with({"id": "7"}, 9222)
