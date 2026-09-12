from unittest.mock import MagicMock

from lib.providers.omni import OmniRouterClient


class TestOmniRouterClient:
    """Тесты для класса OmniRouterClient."""

    def _client(self, **kwargs):
        """Возвращает клиент с замоканным логгером."""
        client = OmniRouterClient(**kwargs)
        client._logger = MagicMock()
        client._logger.get_llm_history.return_value = []
        return client

    def test_name(self):
        """name возвращает название провайдера."""
        assert OmniRouterClient().name == "OmniRouter"

    def test_init_defaults(self):
        """Дефолтные base_url и model."""
        client = self._client()
        assert client._base_url == "http://localhost:20128/v1"
        assert client._model == "auto"

    def test_init_custom_url_strips_slash(self):
        """base_url обрезает завершающий слэш."""
        client = self._client(base_url="http://example.com/v1/")
        assert client._base_url == "http://example.com/v1"

    def test_ask_success(self, mocker):
        """Успешный ответ LLM возвращается."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Ответ системы"}}]
        }
        mock_post = mocker.patch("lib.providers.omni.requests.post")
        mock_post.return_value = mock_response

        client = self._client()
        result = client.ask("Привет")

        assert result == "Ответ системы"
        client._logger.log_llm.assert_any_call("user", "Привет")
        client._logger.log_llm.assert_any_call("assistant", "Ответ системы")

    def test_ask_sends_correct_payload(self, mocker):
        """Payload содержит модель и сообщения системы/пользователя."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "ок"}}]}
        mock_post = mocker.patch("lib.providers.omni.requests.post")
        mock_post.return_value = mock_response
        client = self._client()
        client._logger.get_llm_history.return_value = [
            {"role": "assistant", "content": "прошлый"}
        ]
        client.ask("вопрос")
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["model"] == client._model
        roles = [m["role"] for m in kwargs["json"]["messages"]]
        assert roles == ["system", "assistant", "user"]

    def test_ask_http_error_returns_none(self, mocker):
        """HTTP-ошибка приводит к None."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("500")
        mock_post = mocker.patch("lib.providers.omni.requests.post")
        mock_post.return_value = mock_response
        client = self._client()
        assert client.ask("Привет") is None

    def test_ask_request_exception_returns_none(self, mocker):
        """Исключение при запросе приводит к None."""
        mocker.patch(
            "lib.providers.omni.requests.post", side_effect=ConnectionError("down")
        )
        client = self._client()
        assert client.ask("Привет") is None
