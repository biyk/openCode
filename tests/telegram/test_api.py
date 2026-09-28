"""Тесты клиента Bot API Telegram (lib/telegram/api.py).

Проверяют URL/параметры запросов и то, что сбои сети и ошибки Telegram
не валят вызывающий код: `swallowed()` пишет в лог, методы возвращают
«нет данных» (None), а get_updates — None отдельно от пустого списка
(цикл polling'а по этому различает сбой и тишину).
"""

import pytest

from lib.telegram.api import TelegramApi


@pytest.fixture
def requests_mock(mocker):
    return mocker.patch("lib.telegram.api.requests")


def _ok(mocker, result):
    """Ответ API с ok=true и переданным result."""
    response = mocker.MagicMock()
    response.json.return_value = {"ok": True, "result": result}
    return response


class TestGetUpdates:
    def test_returns_updates_and_passes_params(self, mocker, requests_mock):
        updates = [{"update_id": 5, "message": {"text": "громче"}}]
        requests_mock.post.return_value = _ok(mocker, updates)
        bot = TelegramApi("TOKEN")
        assert bot.get_updates(6, 20) == updates
        url = requests_mock.post.call_args.args[0]
        params = requests_mock.post.call_args.kwargs["params"]
        assert url.endswith("/botTOKEN/getUpdates")
        assert params["offset"] == 6
        assert params["timeout"] == 20
        assert params["allowed_updates"] == '["message"]'

    def test_drops_non_dict_items(self, mocker, requests_mock):
        requests_mock.post.return_value = _ok(mocker, [{"update_id": 1}, "мусор"])
        assert TelegramApi("TOKEN").get_updates(0, 20) == [{"update_id": 1}]

    def test_error_returns_none(self, mocker, requests_mock):
        """ok=false (например, конфликт polling'а) — None, а не пустой список."""
        response = mocker.MagicMock()
        response.json.return_value = {"ok": False,
                                      "description": "Conflict: terminated"}
        requests_mock.post.return_value = response
        swallowed = mocker.patch("lib.telegram.api.swallowed")
        assert TelegramApi("TOKEN").get_updates(0, 20) is None
        assert swallowed.call_args.args[0] == "telegram.getUpdates"

    def test_network_error_is_logged_and_none(self, requests_mock):
        requests_mock.post.side_effect = OSError("no route")
        assert TelegramApi("TOKEN").get_updates(0, 20) is None

    def test_token_never_reaches_the_log(self, mocker, requests_mock):
        """requests пишет URL в ошибку, а URL бота — это его токен."""
        requests_mock.post.side_effect = OSError(
            "Max retries exceeded with url: /botSECRET-TOKEN/getUpdates")
        log = mocker.patch("lib.telegram.api.swallowed")
        assert TelegramApi("SECRET-TOKEN").get_updates(0, 20) is None
        assert "SECRET-TOKEN" not in str(log.call_args.args[1])


class TestProxy:
    def test_proxy_is_passed_to_requests(self, mocker, requests_mock):
        """Без прокси Bot API отсюда недоступен — requests должен его знать."""
        requests_mock.post.return_value = _ok(mocker, {"username": "b"})
        TelegramApi("TOKEN", proxy="socks5h://10.0.0.1:1080").get_me()
        proxies = requests_mock.post.call_args.kwargs["proxies"]
        assert proxies == {"http": "socks5h://10.0.0.1:1080",
                           "https": "socks5h://10.0.0.1:1080"}

    def test_without_proxy_requests_gets_none(self, mocker, requests_mock):
        requests_mock.post.return_value = _ok(mocker, {"username": "b"})
        TelegramApi("TOKEN").get_me()
        assert requests_mock.post.call_args.kwargs["proxies"] is None


class TestSendMessage:
    def test_true_on_accepted(self, mocker, requests_mock):
        requests_mock.post.return_value = _ok(mocker, {"message_id": 12})
        assert TelegramApi("TOKEN").send_message("777", "Готово") is True
        params = requests_mock.post.call_args.kwargs["params"]
        assert params["chat_id"] == "777"
        assert params["text"] == "Готово"

    def test_false_when_rejected(self, mocker, requests_mock):
        response = mocker.MagicMock()
        response.json.return_value = {"ok": False, "description": "400: chat not found"}
        requests_mock.post.return_value = response
        assert TelegramApi("TOKEN").send_message("1", "текст") is False


class TestGetMe:
    def test_username(self, mocker, requests_mock):
        requests_mock.post.return_value = _ok(
            mocker, {"username": "voice_bot"})
        assert TelegramApi("TOKEN").get_me() == "voice_bot"

    def test_short_timeout_is_restored(self, mocker, requests_mock):
        """Свой таймаут проверки токена не «прилипает» к последующим вызовам."""
        requests_mock.post.return_value = _ok(mocker, {"username": "b"})
        bot = TelegramApi("TOKEN", timeout_s=45.0)
        bot.get_me(timeout_s=8.0)
        assert requests_mock.post.call_args.kwargs["timeout"] == 8.0
        bot.get_updates(0, 20)
        assert requests_mock.post.call_args.kwargs["timeout"] == 45.0

    def test_bad_token_returns_none(self, mocker, requests_mock):
        response = mocker.MagicMock()
        response.raise_for_status.side_effect = ValueError("401 Unauthorized")
        requests_mock.post.return_value = response
        assert TelegramApi("TOKEN").get_me() is None
