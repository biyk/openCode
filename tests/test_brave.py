import json
import subprocess
from unittest.mock import MagicMock

import requests

from lib.providers.brave import BraveClient

DEEPSEEK_URL = "https://chat.deepseek.com/"
TAB_URL = "https://chat.deepseek.com/c/abc123"


class TestBraveClient:
    """Тесты для класса BraveClient."""

    def _make(self, mocker, **kwargs):
        """Возвращает клиент с замоканным time.sleep."""
        mocker.patch("lib.providers.brave.time.sleep")
        return BraveClient(**kwargs)

    def test_name(self, mocker):
        """name возвращает название провайдера."""
        client = self._make(mocker)
        assert client.name == "Brave"

    def test_init_debug_port(self, mocker):
        """base_url строится из debug_port."""
        client = self._make(mocker, debug_port=9333)
        assert client._base_url == "http://localhost:9333"

    def test_ask_success(self, mocker):
        """Успешная отправка возвращает ответ."""
        client = self._make(mocker)
        mocker.patch.object(client, "ensure_deepseek_tab", return_value=True)
        mocker.patch.object(client, "send_text_to_input", return_value=(True, "Ответ"))
        assert client.ask("Привет") == "Ответ"

    def test_ask_tab_unavailable_returns_none(self, mocker):
        """Если вкладку не удалось открыть — None."""
        client = self._make(mocker)
        mocker.patch.object(client, "ensure_deepseek_tab", return_value=False)
        assert client.ask("Привет") is None

    def test_ask_send_failed_returns_none(self, mocker):
        """Если отправка не удалась — None."""
        client = self._make(mocker)
        mocker.patch.object(client, "ensure_deepseek_tab", return_value=True)
        mocker.patch.object(client, "send_text_to_input", return_value=(False, ""))
        assert client.ask("Привет") is None

    def test_is_brave_running_true(self, mocker):
        """База отладки отвечает — Brave запущен."""
        client = self._make(mocker)
        mock_get = mocker.patch("lib.providers.brave.requests.get")
        mock_get.return_value.status_code = 200
        assert client._is_brave_running() is True

    def test_is_brave_running_false(self, mocker):
        """ConnectionError — Brave не запущен."""
        client = self._make(mocker)
        mocker.patch(
            "lib.providers.brave.requests.get",
            side_effect=requests.exceptions.ConnectionError("refused"),
        )
        assert client._is_brave_running() is False

    def test_start_brave_success(self, mocker):
        """Браузер запускается и становится готовым."""
        client = self._make(mocker)
        mocker.patch("lib.providers.brave.subprocess.Popen")
        mocker.patch.object(client, "_is_brave_running", return_value=True)
        assert client._start_brave() is True

    def test_start_brave_not_ready(self, mocker):
        """За 30 попыток браузер не готов — False."""
        client = self._make(mocker)
        mocker.patch("lib.providers.brave.subprocess.Popen")
        mocker.patch.object(client, "_is_brave_running", return_value=False)
        assert client._start_brave() is False

    def test_start_brave_not_found(self, mocker):
        """brave-browser отсутствует в PATH — False."""
        client = self._make(mocker)
        mocker.patch(
            "lib.providers.brave.subprocess.Popen",
            side_effect=FileNotFoundError,
        )
        assert client._start_brave() is False

    def test_start_brave_generic_error(self, mocker):
        """Прочая ошибка запуска — False."""
        client = self._make(mocker)
        mocker.patch(
            "lib.providers.brave.subprocess.Popen",
            side_effect=RuntimeError("oops"),
        )
        assert client._start_brave() is False

    def test_get_tabs_success(self, mocker):
        """Список вкладок возвращается из ответа API."""
        client = self._make(mocker)
        tabs = [{"title": "DeepSeek", "url": DEEPSEEK_URL}]
        mock_get = mocker.patch("lib.providers.brave.requests.get")
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = tabs
        assert client._get_tabs() == tabs

    def test_get_tabs_error(self, mocker):
        """Ошибка получения вкладок — пустой список."""
        client = self._make(mocker)
        mocker.patch(
            "lib.providers.brave.requests.get",
            side_effect=requests.exceptions.ConnectionError("down"),
        )
        assert client._get_tabs() == []

    def test_find_deepseek_tab_found(self, mocker):
        """Вкладка DeepSeek находится по URL."""
        client = self._make(mocker)
        tab = {"title": "DeepSeek", "url": TAB_URL}
        mocker.patch.object(client, "_get_tabs", return_value=[tab])
        assert client._find_deepseek_tab() == tab

    def test_find_deepseek_tab_not_found(self, mocker):
        """Если вкладок нет — None."""
        client = self._make(mocker)
        mocker.patch.object(
            client, "_get_tabs",
            return_value=[{"url": "https://google.com"}],
        )
        assert client._find_deepseek_tab() is None

    def test_switch_to_tab_success(self, mocker):
        """Переключение вкладки успешно."""
        client = self._make(mocker)
        mocker.patch("lib.providers.brave.requests.post")
        assert client._switch_to_tab("tab1") is True

    def test_switch_to_tab_error(self, mocker):
        """Ошибка переключения — False."""
        client = self._make(mocker)
        mocker.patch(
            "lib.providers.brave.requests.post",
            side_effect=requests.exceptions.ConnectionError("down"),
        )
        assert client._switch_to_tab("tab1") is False

    def test_navigate_tab_success(self, mocker):
        """Навигация с кодом 200 — True."""
        client = self._make(mocker)
        mock_post = mocker.patch("lib.providers.brave.requests.post")
        mock_post.return_value.status_code = 200
        assert client._navigate_tab("tab1", DEEPSEEK_URL) is True

    def test_navigate_tab_bad_status(self, mocker):
        """Навигация с не-200 кодом — False."""
        client = self._make(mocker)
        mock_post = mocker.patch("lib.providers.brave.requests.post")
        mock_post.return_value.status_code = 500
        assert client._navigate_tab("tab1", DEEPSEEK_URL) is False

    def test_navigate_tab_error(self, mocker):
        """Ошибка навигации — False."""
        client = self._make(mocker)
        mocker.patch(
            "lib.providers.brave.requests.post",
            side_effect=requests.exceptions.ConnectionError("down"),
        )
        assert client._navigate_tab("tab1", DEEPSEEK_URL) is False

    def test_open_deepseek_success(self, mocker):
        """Открытие вкладки DeepSeek с кодом 200."""
        client = self._make(mocker)
        mock_get = mocker.patch("lib.providers.brave.requests.get")
        mock_get.return_value.status_code = 200
        mock_get.return_value.text = "{}"
        assert client._open_deepseek() is True

    def test_open_deepseek_bad_status(self, mocker):
        """Открытие вкладки с не-200 кодом — False."""
        client = self._make(mocker)
        mock_get = mocker.patch("lib.providers.brave.requests.get")
        mock_get.return_value.status_code = 400
        assert client._open_deepseek() is False

    def test_open_deepseek_error(self, mocker):
        """Ошибка открытия вкладки — False."""
        client = self._make(mocker)
        mocker.patch(
            "lib.providers.brave.requests.get",
            side_effect=requests.exceptions.ConnectionError("down"),
        )
        assert client._open_deepseek() is False

    def test_ensure_tab_start_fails(self, mocker):
        """Если запуск браузера провалился — False."""
        client = self._make(mocker)
        mocker.patch.object(client, "_is_brave_running", return_value=False)
        mocker.patch.object(client, "_start_brave", return_value=False)
        assert client.ensure_deepseek_tab() is False

    def test_ensure_tab_start_ok_found_exact(self, mocker):
        """Браузер запущен, вкладка с точным URL найдена."""
        client = self._make(mocker)
        mocker.patch.object(client, "_is_brave_running", side_effect=[False, True])
        mocker.patch.object(client, "_start_brave", return_value=True)
        tab = {"id": "1", "title": "DeepSeek", "url": DEEPSEEK_URL}
        mocker.patch.object(client, "_find_deepseek_tab", return_value=tab)
        switch = mocker.patch.object(client, "_switch_to_tab")
        navigate = mocker.patch.object(client, "_navigate_tab")
        assert client.ensure_deepseek_tab() is True
        switch.assert_called_once_with("1")
        navigate.assert_not_called()

    def test_ensure_tab_found_requires_navigate(self, mocker):
        """Вкладка найдена, но требуется переход по URL."""
        client = self._make(mocker)
        mocker.patch.object(client, "_is_brave_running", return_value=True)
        tab = {"id": "2", "title": "DeepSeek", "url": TAB_URL}
        mocker.patch.object(client, "_find_deepseek_tab", return_value=tab)
        mocker.patch.object(client, "_switch_to_tab", return_value=True)
        navigate = mocker.patch.object(client, "_navigate_tab", return_value=True)
        assert client.ensure_deepseek_tab() is True
        navigate.assert_called_once_with("2", DEEPSEEK_URL)

    def test_ensure_tab_open_when_missing(self, mocker):
        """Вкладки нет — открывается новая."""
        client = self._make(mocker)
        mocker.patch.object(client, "_is_brave_running", return_value=True)
        mocker.patch.object(client, "_find_deepseek_tab", return_value=None)
        mocker.patch.object(client, "_open_deepseek", return_value=True)
        assert client.ensure_deepseek_tab() is True

    def test_ensure_tab_open_fails(self, mocker):
        """Открытие новой вкладки провалилось — False."""
        client = self._make(mocker)
        mocker.patch.object(client, "_is_brave_running", return_value=True)
        mocker.patch.object(client, "_find_deepseek_tab", return_value=None)
        mocker.patch.object(client, "_open_deepseek", return_value=False)
        assert client.ensure_deepseek_tab() is False

    def test_focus_wmctrl_success(self, mocker):
        """Фокус через wmctrl с кодом 0."""
        client = self._make(mocker)
        mock_run = mocker.patch("lib.providers.brave.subprocess.run")
        mock_run.return_value.returncode = 0
        assert client._focus_brave_window() is True

    def test_focus_wmctrl_bad_rc(self, mocker):
        """Фокус через wmctrl с ненулевым кодом — False."""
        client = self._make(mocker)
        mock_run = mocker.patch("lib.providers.brave.subprocess.run")
        mock_run.return_value.returncode = 1
        assert client._focus_brave_window() is False

    def test_focus_fallback_xdotool_success(self, mocker):
        """Если wmctrl нет, фокус через xdotool."""
        client = self._make(mocker)
        mock_run = mocker.patch("lib.providers.brave.subprocess.run")
        mock_run.side_effect = [FileNotFoundError, MagicMock(returncode=0)]
        assert client._focus_brave_window() is True

    def test_focus_xdotool_error(self, mocker):
        """Ошибка xdotool — False."""
        client = self._make(mocker)
        mock_run = mocker.patch("lib.providers.brave.subprocess.run")
        mock_run.side_effect = [FileNotFoundError, RuntimeError("no X")]
        assert client._focus_brave_window() is False

    def test_focus_generic_error(self, mocker):
        """Прочая ошибка фокусировки — False."""
        client = self._make(mocker)
        mock_run = mocker.patch("lib.providers.brave.subprocess.run")
        mock_run.side_effect = subprocess.TimeoutExpired("wmctrl", 5)
        assert client._focus_brave_window() is False

    def test_send_text_no_tab(self, mocker):
        """Без вкладки отправка возвращает (False, '')."""
        client = self._make(mocker)
        mocker.patch.object(client, "_find_deepseek_tab", return_value=None)
        assert client.send_text_to_input("Привет") == (False, "")

    def test_send_text_success(self, mocker):
        """Текст отправляется и приходит ответ."""
        client = self._make(mocker)
        tab = {"id": "1", "url": DEEPSEEK_URL}
        mocker.patch.object(client, "_find_deepseek_tab", return_value=tab)
        mocker.patch.object(client, "_wait_for_response", return_value=(True, "Ответ"))
        mocker.patch("lib.providers.brave.pyautogui")
        mocker.patch("lib.providers.brave.pyperclip")
        assert client.send_text_to_input("Привет") == (True, "Ответ")

    def test_get_ws_url_found(self, mocker):
        """WS-URL вкладки DeepSeek возвращается."""
        client = self._make(mocker)
        tab = {"url": TAB_URL, "webSocketDebuggerUrl": "ws://debug"}
        mocker.patch.object(client, "_get_tabs", return_value=[tab])
        assert client._get_ws_url() == "ws://debug"

    def test_get_ws_url_not_found(self, mocker):
        """Если вкладки DeepSeek нет — None."""
        client = self._make(mocker)
        mocker.patch.object(client, "_get_tabs", return_value=[])
        assert client._get_ws_url() is None

    def test_execute_js_object_value(self, mocker):
        """Ответ с type=object возвращает value."""
        client = self._make(mocker)
        ws = MagicMock()
        ws.recv.return_value = json.dumps(
            {"id": 1, "result": {"result": {"type": "object", "value": {"k": 1}}}}
        )
        assert client._execute_js(ws, 1, "script") == {"k": 1}

    def test_execute_js_non_object(self, mocker):
        """Ответ с другим типом возвращает весь result."""
        client = self._make(mocker)
        ws = MagicMock()
        ws.recv.return_value = json.dumps(
            {"id": 1, "result": {"result": {"type": "string", "value": "abc"}}}
        )
        result = client._execute_js(ws, 1, "script")
        assert result == {"type": "string", "value": "abc"}

    def test_execute_js_no_match(self, mocker):
        """Если id не совпал за 20 ответов — None."""
        client = self._make(mocker)
        ws = MagicMock()
        ws.recv.return_value = json.dumps(
            {"id": 999, "result": {"result": {"type": "object"}}}
        )
        assert client._execute_js(ws, 1, "script") is None

    def test_execute_js_error(self, mocker):
        """Ошибка WebSocket — None."""
        client = self._make(mocker)
        ws = MagicMock()
        ws.recv.side_effect = RuntimeError("broken")
        assert client._execute_js(ws, 1, "script") is None

    def test_wait_response_no_ws_url(self, mocker):
        """Без WS-URL — (False, '')."""
        client = self._make(mocker)
        mocker.patch.object(client, "_get_ws_url", return_value=None)
        assert client._wait_for_response() == (False, "")

    def test_wait_response_success(self, mocker):
        """Успешный ответ от DeepSeek."""
        client = self._make(mocker)
        mocker.patch.object(client, "_get_ws_url", return_value="ws://debug")
        ws = MagicMock()
        mocker.patch(
            "lib.providers.brave.websocket.create_connection", return_value=ws
        )
        mocker.patch.object(
            client, "_execute_js",
            return_value={"ready": True, "content": "Готово"},
        )
        assert client._wait_for_response() == (True, "Готово")
        ws.close.assert_called_once()

    def test_wait_response_timeout(self, mocker):
        """Таймаут ожидания — (False, '')."""
        client = self._make(mocker)
        mocker.patch.object(client, "_get_ws_url", return_value="ws://debug")
        ws = MagicMock()
        mocker.patch(
            "lib.providers.brave.websocket.create_connection", return_value=ws
        )
        mocker.patch.object(
            client, "_execute_js",
            return_value={"ready": False},
        )
        assert client._wait_for_response() == (False, "")

    def test_wait_response_exception(self, mocker):
        """Исключение при ожидании — (False, '')."""
        client = self._make(mocker)
        mocker.patch.object(client, "_get_ws_url", return_value="ws://debug")
        mocker.patch(
            "lib.providers.brave.websocket.create_connection",
            side_effect=RuntimeError("broken"),
        )
        assert client._wait_for_response() == (False, "")
