from unittest.mock import MagicMock

from lib.providers.deepseek import DeepSeekClient


class TestDeepSeekClient:
    """Тесты для класса DeepSeekClient."""

    def _client(self, **kwargs):
        """Возвращает клиент с замоканным логгером."""
        client = DeepSeekClient(**kwargs)
        client._logger = MagicMock()
        client._logger.get_llm_history.return_value = []
        return client

    def test_name(self):
        """name возвращает название провайдера."""
        assert self._client(api_key="k").name == "DeepSeek"

    def test_init_with_api_key(self):
        """api_key передаётся в конструктор."""
        client = self._client(api_key="secret")
        assert client._api_key == "secret"

    def test_ask_without_api_key_returns_none(self, mocker):
        """Без ключа ask возвращает None и ничего не отправляет."""
        mocker.patch("lib.providers.deepseek.requests.post")
        mocker.patch("lib.providers.deepseek.os.getenv", return_value=None)
        client = self._client(api_key=None)
        assert client.ask("hello") is None

    def test_ask_success(self, mocker):
        """Успешный ответ LLM возвращается."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Понял"}}]
        }
        mock_post = mocker.patch("lib.providers.deepseek.requests.post")
        mock_post.return_value = mock_response

        client = self._client(api_key="secret")
        result = client.ask("Привет")

        assert result == "Понял"
        client._logger.log_llm.assert_any_call("user", "Привет")
        client._logger.log_llm.assert_any_call("assistant", "Понял")

    def test_ask_api_error_returns_none(self, mocker):
        """HTTP-ошибка приводит к None."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("400")
        mock_post = mocker.patch("lib.providers.deepseek.requests.post")
        mock_post.return_value = mock_response
        client = self._client(api_key="secret")
        assert client.ask("Привет") is None
