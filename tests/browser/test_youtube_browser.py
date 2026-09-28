# TOOLTIP: Тесты сценариев YouTube: поиск и первый результат по событиям
"""Тесты для lib/browser/youtube_browser.py (поиск и первый результат).

Ожидания `cdp_events` заглушены: проверяется порядок шагов сценария, а не
работа WebSocket (это test_cdp_events.py). Сценарий «открой юту» — в
test_youtube_open_first.py.
"""

import urllib.parse

import pytest

from lib.browser import youtube_browser as ytb

TAB = {"id": "1", "url": "https://www.youtube.com/"}


@pytest.fixture(autouse=True)
def events(mocker):
    """Все ожидания страницы успешны, пока тест не задал обратного."""
    return mocker.patch.multiple(
        ytb.cde,
        wait_page_loaded=mocker.DEFAULT, wait_element=mocker.DEFAULT,
        wait_condition=mocker.DEFAULT, navigate=mocker.DEFAULT)


@pytest.fixture(autouse=True)
def no_browser(mocker):
    """Активация вкладки и запросы к ней не идут в живой браузер."""
    mocker.patch("lib.browser.cdp_client._activate")
    return mocker.patch("lib.browser.cdp_client.eval_js",
                        return_value=(True, "playing"))


class TestYoutubeSearch:
    """Поиск и проигрывание первого результата."""

    def test_search_builds_url_and_waits_results(self, mocker, events):
        """Строит url поиска и ждёт результаты, а не спит 3 секунды."""
        mock_open = mocker.patch("lib.browser_control.open_url",
                                 return_value=TAB)
        ytb.youtube_search("музыка")
        url = mock_open.call_args[0][0]
        assert "youtube.com/results" in url
        assert urllib.parse.unquote(url).find("музыка") >= 0
        events["wait_page_loaded"].assert_called_once()
        events["wait_element"].assert_called_once()

    def test_search_without_tab_skips_waits(self, mocker, events):
        """Вкладки нет — ждать нечего, исключения нет."""
        mocker.patch("lib.browser_control.open_url", return_value=None)
        assert ytb.youtube_search("музыка") is None
        events["wait_element"].assert_not_called()

    def test_play_runs_both_stages(self, mocker):
        """youtube_play выполняет обе стадии."""
        mocker.patch("lib.browser.youtube_browser.youtube_search",
                     return_value=TAB)
        mock_first = mocker.patch(
            "lib.browser.youtube_browser.youtube_play_first_result",
            return_value=True)
        assert ytb.youtube_play("музыка") is True
        mock_first.assert_called_once()

    def test_play_without_tab(self, mocker):
        """youtube_play возвращает False без вкладки."""
        mocker.patch("lib.browser.youtube_browser.youtube_search",
                     return_value=None)
        assert ytb.youtube_play("музыка") is False

    def test_play_first_result_clicks_and_plays(self, mocker, events):
        """Результат найден → клик → плеер → подтверждение воспроизведения."""
        mock_click = mocker.patch("lib.browser.cdp_client.click",
                                  return_value=(True, "__CLICKED__"))
        assert ytb.youtube_play_first_result(TAB) is True
        mock_click.assert_called_once()
        assert events["wait_condition"].called

    def test_play_first_result_waits_results(self, mocker, events):
        """Результаты не загрузились — сценарий прекращается сразу."""
        events["wait_element"].return_value = False
        assert ytb.youtube_play_first_result(TAB) is False

    def test_play_first_result_click_fails(self, mocker):
        """Клик мимо результата — неуспех, плеер не ждём."""
        mocker.patch("lib.browser.cdp_client.click",
                     return_value=(False, "элемент не найден"))
        assert ytb.youtube_play_first_result(TAB) is False


class TestHelpers:
    """Мелкие вспомогательные функции."""

    def test_is_watch_url(self):
        assert ytb._youtube_is_watch("https://youtube.com/watch?v=1") is True
        assert ytb._youtube_is_watch("https://youtube.com/shorts/1") is True
        assert ytb._youtube_is_watch("https://youtube.com/results?q=1") is False

    def test_first_video_link_empty_on_error(self, mocker):
        mocker.patch("lib.browser.cdp_client.eval_js",
                     return_value=(False, "нет вкладки"))
        assert ytb._youtube_first_video_link(TAB) == ""

    def test_page_tabs_filters_non_pages(self, mocker):
        """Вкладки ютуба: service worker чужой, обычные страницы — свои."""
        tabs = [{"id": "1", "type": "page", "url": "https://youtube.com"},
                {"id": "2", "type": "service_worker", "url": "https://youtube.com/sw"},
                {"id": "3", "type": "page", "url": "https://example.com"}]
        mocker.patch("lib.browser.cdp_client._list_tabs", return_value=tabs)
        assert [t["id"] for t in ytb._youtube_page_tabs()] == ["1"]
