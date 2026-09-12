from unittest.mock import MagicMock

from lib.providers.gpt4free import Gpt4FreeClient


class TestGpt4FreeClient:
    """Тесты для класса Gpt4FreeClient."""

    def _make_client(self, mocker):
        """Возвращает клиент с замоканным backend и логгером."""
        mock_backend = MagicMock()
        mocker.patch("lib.providers.gpt4free.Client", return_value=mock_backend)
        client = Gpt4FreeClient()
        client._logger = MagicMock()
        client._logger.get_llm_history.return_value = []
        return client, mock_backend

    def test_name(self, mocker):
        """name возвращает название провайдера."""
        client, _ = self._make_client(mocker)
        assert client.name == "GPT4Free"

    def test_init_with_custom_model(self, mocker):
        """Кастомная модель сохраняется в клиенте."""
        mocker.patch("lib.providers.gpt4free.Client", return_value=MagicMock())
        client = Gpt4FreeClient(model="gpt-4o")
        assert client._model == "gpt-4o"

    def test_ask_success(self, mocker):
        """Успешный ответ LLM возвращается."""
        client, mock_backend = self._make_client(mocker)
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Привет, человек"
        mock_backend.chat.completions.create.return_value = mock_response

        result = client.ask("Здравствуй")

        assert result == "Привет, человек"
        client._logger.log_llm.assert_any_call("user", "Здравствуй")
        client._logger.log_llm.assert_any_call("assistant", "Привет, человек")

    def test_ask_sends_messages(self, mocker):
        """Запрос содержит model и messages без web_search."""
        client, mock_backend = self._make_client(mocker)
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "ок"
        mock_backend.chat.completions.create.return_value = mock_response

        client.ask("вопрос")

        _, kwargs = mock_backend.chat.completions.create.call_args
        assert kwargs["model"] == "gpt-4o-mini"
        assert kwargs["web_search"] is False

    def test_ask_api_error_returns_none(self, mocker):
        """Ошибка вызова приводит к None."""
        client, mock_backend = self._make_client(mocker)
        mock_backend.chat.completions.create.side_effect = RuntimeError("down")
        assert client.ask("вопрос") is None
