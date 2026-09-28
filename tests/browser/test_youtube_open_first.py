# TOOLTIP: Тесты сценария «открой юту»: ожидание плеера по событиям, запуск ролика
"""Регресс «открой юту → Не удалось запустить текущее видео» (youtube_browser).

Вкладка сразу после старта браузера ещё грузится, поэтому сценарий обязан
идать по событиям страницы: загрузка → `<video>` в DOM → подтверждение, что
плеер реально играет. Ожидания `cdp_events` заглушены — здесь проверяется
порядок шагов, а не работа WebSocket (это test_cdp_events.py).
"""

import pytest

from lib.browser import youtube_browser as ytb

WATCH_TAB = {"id": "1", "type": "page",
             "url": "https://www.youtube.com/watch?v=abc"}
HOME_TAB = {"id": "2", "type": "page", "url": "https://www.youtube.com/"}


@pytest.fixture(autouse=True)
def events(mocker):
    """Все событийные ожидания страницы успешны, пока тест не задал иное."""
    return mocker.patch.multiple(
        ytb.cde,
        wait_page_loaded=mocker.DEFAULT, wait_element=mocker.DEFAULT,
        wait_condition=mocker.DEFAULT, navigate=mocker.DEFAULT)


@pytest.fixture(autouse=True)
def no_browser(mocker):
    """Ни один запрос не уходит в живой браузер."""
    mocker.patch("lib.browser.cdp_client._activate")
    mocker.patch("lib.browser.cdp_client.eval_js",
                 return_value=(True, "playing"))
    mocker.patch("lib.browser_control.ensure_browser", return_value=True)
    return mocker.patch("lib.browser.cdp_client._list_tabs", return_value=[])


class TestPlayerReady:
    """Ожидание плеера на вкладке."""

    def test_player_ready_first_try(self, events):
        assert ytb._wait_player_ready({"id": "1"}) is True
        assert events["wait_page_loaded"].call_count == 1
        assert events["wait_element"].call_count == 1

    def test_player_ready_second_try(self, mocker, events):
        """Первая проба — документ-заглушка навигации: со второй ролик есть."""
        events["wait_element"].side_effect = [False, True]
        assert ytb._wait_player_ready({"id": "1"}) is True
        assert events["wait_element"].call_count == 2

    def test_player_never_appears(self, mocker, events):
        """Плеера так и нет — успехом усталость ожидания не считаем."""
        events["wait_element"].side_effect = [False, False]
        assert ytb._wait_player_ready({"id": "1"}) is False


class TestResume:
    """Запуск уже открытого ролика."""

    def test_resume_waits_player_before_play(self, mocker, events):
        """Страница грузится: без <video> плей не жмём и не считаем успехом."""
        events["wait_element"].return_value = False
        play = mocker.patch("lib.browser.youtube_browser._try_play",
                            return_value=True)
        assert ytb._youtube_resume_current(WATCH_TAB) is False
        play.assert_not_called()

    def test_resume_requires_playing(self, mocker, events):
        """Скрипт сказал «playing», а страница на паузе — воспроизведения нет."""
        events["wait_condition"].return_value = False
        assert ytb._youtube_resume_current(WATCH_TAB) is False

    def test_resume_falls_back_to_play_button(self, mocker, events):
        """Play() заблокирован без жеста — кликаем кнопку и верим состоянию."""
        events["wait_condition"].side_effect = [False, True]
        mock_click = mocker.patch("lib.browser.cdp_client.click",
                                  return_value=(True, "__CLICKED__"))
        assert ytb._youtube_resume_current(WATCH_TAB) is True
        mock_click.assert_called_once_with(
            WATCH_TAB, ytb._YOUTUBE_SELECTORS["player"])


class TestOpenFirst:
    """Сценарий «открыть или запустить ютуб»."""

    def test_no_tabs_opens_home_and_video(self, mocker, events, no_browser):
        """Вкладок ютуба нет — главная, лента, первое видео из неё."""
        tab = {"id": "1", "url": "https://www.youtube.com/"}
        mocker.patch("lib.browser_control.open_url", return_value=tab)
        link = "https://www.youtube.com/watch?v=abc"
        mock_link = mocker.patch(
            "lib.browser.youtube_browser._youtube_first_video_link",
            return_value=link)
        assert ytb.youtube_open_first() is True
        # ленту ждём событием, ссылку читаем только после неё
        feed = ytb._YOUTUBE_SELECTORS["feed"]
        assert events["wait_element"].call_args_list[0][0][1] == feed
        mock_link.assert_called_once()
        events["navigate"].assert_called_once_with(tab, link)

    def test_feed_not_loaded(self, mocker, events):
        """Лента не появилась — ни ссылок, ни перехода."""
        mocker.patch("lib.browser_control.open_url", return_value=HOME_TAB)
        events["wait_element"].return_value = False
        mock_link = mocker.patch(
            "lib.browser.youtube_browser._youtube_first_video_link")
        assert ytb.youtube_open_first() is False
        mock_link.assert_not_called()

    def test_no_link_after_feed(self, mocker, events):
        """Элемент есть, а ссылки нет — переход не делаем."""
        mocker.patch("lib.browser_control.open_url", return_value=HOME_TAB)
        mocker.patch("lib.browser.youtube_browser._youtube_first_video_link",
                     return_value="")
        assert ytb.youtube_open_first() is False
        events["navigate"].assert_not_called()

    def test_open_first_no_tab(self, mocker):
        """Без вкладки сценарий не продолжается."""
        mocker.patch("lib.browser_control.open_url", return_value=None)
        assert ytb.youtube_open_first() is False

    def test_open_first_needs_browser(self, mocker):
        """Браузер не поднялся — ничего не открываем."""
        mocker.patch("lib.browser_control.ensure_browser", return_value=False)
        mock_open = mocker.patch("lib.browser_control.open_url")
        assert ytb.youtube_open_first() is False
        mock_open.assert_not_called()

    def test_open_first_resumes_watch(self, mocker, events, no_browser):
        """Есть вкладка с роликом — запускаем её, новую не открываем."""
        no_browser.return_value = [WATCH_TAB]
        mock_open = mocker.patch("lib.browser_control.open_url")
        assert ytb.youtube_open_first() is True
        mock_open.assert_not_called()
        assert events["wait_page_loaded"].called
        assert events["wait_condition"].called

    def test_open_first_home_opens_first(self, mocker, events, no_browser):
        """Главная уже открыта — берём видео из ленты этой вкладки."""
        no_browser.return_value = [HOME_TAB]
        mock_open = mocker.patch("lib.browser_control.open_url")
        mocker.patch("lib.browser.youtube_browser._youtube_first_video_link",
                     return_value="https://www.youtube.com/watch?v=abc")
        assert ytb.youtube_open_first() is True
        mock_open.assert_not_called()

    def test_open_first_prefers_watch_over_home(self, mocker, events,
                                                no_browser):
        """При главной и ролике — запускает ролик, не трогая ленту."""
        worker = {"id": "3", "type": "service_worker",
                  "url": "https://www.youtube.com/sw.js"}
        no_browser.return_value = [worker, HOME_TAB, WATCH_TAB]
        mock_open = mocker.patch("lib.browser_control.open_url")
        mock_wait = mocker.patch(
            "lib.browser.youtube_browser._youtube_wait_and_open_first")
        mock_resume = mocker.patch(
            "lib.browser.youtube_browser._youtube_resume_current",
            return_value=True)
        assert ytb.youtube_open_first() is True
        mock_resume.assert_called_once_with(WATCH_TAB, 9222)
        mock_wait.assert_not_called()
        mock_open.assert_not_called()
