import pytest
from unittest.mock import patch, MagicMock
from lib.openrouter import OpenRouterClient


class TestOpenRouterClient:
    """Тесты для класса OpenRouterClient."""

    def test_init_without_api_key(self):
        with patch('lib.openrouter.os.getenv', return_value=None):
            with patch('lib.openrouter.load_dotenv'):
                from lib.openrouter import OpenRouterClient
                client = OpenRouterClient(api_key=None)
                assert client._api_key is None or client._api_key == ""

    def test_init_with_api_key(self):
        client = OpenRouterClient(api_key="test_key_123")
        assert client._api_key == "test_key_123"

    def test_ask_no_api_key(self):
        client = OpenRouterClient(api_key=None)
        with patch.object(client, '_api_key', None):
            result = client.ask("test")
            assert result is None

    @patch('lib.openrouter.requests.post')
    def test_ask_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {"message": {"content": "Привет! Как дела?"}}
            ]
        }
        mock_post.return_value = mock_response

        client = OpenRouterClient(api_key="test_key")
        result = client.ask("Привет")

        assert result == "Привет! Как дела?"
        mock_post.assert_called_once()

    @patch('lib.openrouter.requests.post')
    def test_ask_api_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_response.raise_for_status.side_effect = Exception("400 Bad Request")
        mock_post.return_value = mock_response

        client = OpenRouterClient(api_key="test_key")
        result = client.ask("test")

        assert result is None

    def test_base_url(self):
        client = OpenRouterClient(api_key="test")
        assert client._base_url == "https://openrouter.ai/api/v1/chat/completions"
