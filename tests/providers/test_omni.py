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

    def test_set_output(self):
        """_set_output сохраняет output для debug-логирования."""
        client = self._client()
        mock_output = MagicMock()
        client._set_output(mock_output)
        assert client._output == mock_output

    def test_ask_logs_request_and_response_debug(self, mocker):
        """При успешном ответе логируются запрос и ответ через print_debug."""
        mock_output = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Ответ системы"}}]
        }
        mock_post = mocker.patch("lib.providers.omni.requests.post")
        mock_post.return_value = mock_response

        client = self._client()
        client._set_output(mock_output)
        result = client.ask("Привет")

        assert result == "Ответ системы"
        assert mock_output.print_debug.call_count == 3
        req_call = mock_output.print_debug.call_args_list[0][0][0]
        assert "[LLM Request]" in req_call
        assert "model=" in req_call
        assert "messages=" in req_call
        status_call = mock_output.print_debug.call_args_list[1][0][0]
        assert "[LLM Status]" in status_call
        resp_call = mock_output.print_debug.call_args_list[2][0][0]
        assert "[LLM Response]" in resp_call
        assert "Ответ системы" in resp_call

    def test_ask_logs_error_debug(self, mocker):
        """При ошибке запроса логируется запрос и ошибка через print_debug."""
        mock_output = MagicMock()
        mocker.patch(
            "lib.providers.omni.requests.post", side_effect=ConnectionError("down")
        )
        client = self._client()
        client._set_output(mock_output)
        result = client.ask("Привет")

        assert result is None
        assert mock_output.print_debug.call_count == 2
        req_call = mock_output.print_debug.call_args_list[0][0][0]
        assert "[LLM Request]" in req_call
        error_call = mock_output.print_debug.call_args_list[1][0][0]
        assert "[LLM Error]" in error_call

    def test_ask_announces_via_print_info_when_enabled(self, mocker):
        """При announce=True и заданном output печатается print_info с именем+моделью."""
        mock_output = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ответ"}}]
        }
        mocker.patch("lib.providers.omni.requests.post", return_value=mock_response)
        client = self._client()
        client._set_output(mock_output)
        client.ask("Привет")
        assert mock_output.print_info.call_count == 1
        info_call = mock_output.print_info.call_args_list[0][0][0]
        assert "[LLM]" in info_call
        assert "OmniRouter" in info_call
        assert "auto" in info_call

    def test_ask_not_announces_when_disabled(self, mocker):
        """При announce=False print_info не вызывается (используется в Race)."""
        mock_output = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ответ"}}]
        }
        mocker.patch("lib.providers.omni.requests.post", return_value=mock_response)
        client = self._client(announce=False)
        client._set_output(mock_output)
        client.ask("Привет")
        assert mock_output.print_info.call_count == 0
