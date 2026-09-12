import base64
import time
from unittest.mock import MagicMock

from lib.providers.gigachat import GigaChatClient


class TestGigaChatClient:
    """Тесты для класса GigaChatClient."""

    def _client(self, api_key="secret", client_id="cid", scope="SCOPE", **kwargs):
        """Возвращает клиент с ключами и замоканным логгером."""
        client = GigaChatClient(api_key=api_key, client_id=client_id, scope=scope, **kwargs)
        client._logger = MagicMock()
        client._logger.get_llm_history.return_value = []
        return client

    def test_name(self):
        """name возвращает название провайдера."""
        assert self._client().name == "GigaChat"

    def test_token_cached_returns_without_request(self, mocker):
        """Действующий кэшированный токен возвращается без запроса."""
        client = self._client()
        client._access_token = "tok"
        client._token_expires_at = time.time() + 1000
        mock_post = mocker.patch("lib.providers.gigachat.requests.post")
        assert client._get_access_token() == "tok"
        mock_post.assert_not_called()

    def test_token_without_credentials_returns_none(self, mocker):
        """Без api_key или client_id токен не получить."""
        mocker.patch("lib.providers.gigachat.os.getenv", return_value=None)
        client = GigaChatClient()
        client._logger = MagicMock()
        assert client._get_access_token() is None

    def test_token_success(self, mocker):
        """Успешное получение токена сохраняется в кэш."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok", "expires_in": 1800}
        mock_post = mocker.patch("lib.providers.gigachat.requests.post")
        mock_post.return_value = mock_response

        key = base64.b64encode(b"client:secret").decode()
        client = self._client(api_key=key)
        assert client._get_access_token() == "tok"
        assert client._token_expires_at > time.time()

    def test_token_invalid_base64_uses_raw_key(self, mocker):
        """Некорректный base64 в ключе не ломает авторизацию."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok", "expires_in": 1800}
        mock_post = mocker.patch("lib.providers.gigachat.requests.post")
        mock_post.return_value = mock_response

        client = self._client(api_key="!!!")
        assert client._get_access_token() == "tok"

    def test_token_request_error_returns_none(self, mocker):
        """Ошибка запроса токена приводит к None."""
        mocker.patch(
            "lib.providers.gigachat.requests.post",
            side_effect=RuntimeError("network"),
        )
        client = self._client()
        assert client._get_access_token() is None

    def test_get_models_success(self, mocker):
        """Список моделей возвращается из ответа API."""
        client = self._client()
        client._access_token = "tok"
        client._token_expires_at = time.time() + 1000
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": ["GigaChat", "GigaChat-Pro"]}
        mock_get = mocker.patch("lib.providers.gigachat.requests.get")
        mock_get.return_value = mock_response
        assert client._get_models() == ["GigaChat", "GigaChat-Pro"]

    def test_get_models_without_token_returns_none(self, mocker):
        """Без токена список моделей не получить."""
        client = self._client()
        mocker.patch.object(client, "_get_access_token", return_value=None)
        assert client._get_models() is None

    def test_get_models_error_returns_none(self, mocker):
        """Ошибка получения моделей приводит к None."""
        client = self._client()
        client._access_token = "tok"
        client._token_expires_at = time.time() + 1000
        mocker.patch(
            "lib.providers.gigachat.requests.get",
            side_effect=RuntimeError("network"),
        )
        assert client._get_models() is None

    def test_ask_success(self, mocker):
        """Успешный ответ GigaChat возвращается."""
        client = self._client()
        client._access_token = "tok"
        client._token_expires_at = time.time() + 1000
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Добрый день"}}]
        }
        mock_post = mocker.patch("lib.providers.gigachat.requests.post")
        mock_post.return_value = mock_response
        result = client.ask("Как дела?")
        assert result == "Добрый день"
        client._logger.log_llm.assert_any_call("user", "Как дела?")

    def test_ask_without_token_returns_none(self, mocker):
        """Без токена ask возвращает None."""
        client = self._client()
        mocker.patch.object(client, "_get_access_token", return_value=None)
        assert client.ask("Как дела?") is None

    def test_ask_api_error_returns_none(self, mocker):
        """HTTP-ошибка ask приводит к None."""
        client = self._client()
        client._access_token = "tok"
        client._token_expires_at = time.time() + 1000
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("500")
        mock_post = mocker.patch("lib.providers.gigachat.requests.post")
        mock_post.return_value = mock_response
        assert client.ask("Как дела?") is None
