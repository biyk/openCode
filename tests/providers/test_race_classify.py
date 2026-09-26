"""Тесты RaceClient: classify."""


import threading
from unittest.mock import MagicMock
from lib.providers.race import RaceClient


class TestRaceClassify:
    """classify: пропуск пустых, анонсы, таймаут."""

    @staticmethod
    def _block_forever():
        """Блокирует поток навсегда (для теста таймаута)."""
        threading.Event().wait(30)

    def test_classify_skips_none_waits_for_answer(self, mocker):
        """Быстрый NONE не убивает медленный правильный ответ."""
        import time

        client = RaceClient()
        client._logger = MagicMock()

        client._lmstudio.ask = lambda text: "NONE"
        client._omni.ask = lambda text: time.sleep(0.1) or "playpause"

        assert client.classify("паузы пожалуйста") == "playpause"

    def test_classify_all_none_returns_none(self, mocker):
        """Оба ответили NONE — возвращается None."""
        client = RaceClient()
        client._logger = MagicMock()

        client._omni.ask = lambda text: "NONE"
        client._lmstudio.ask = lambda text: "none"

        assert client.classify("что-то") is None

    def test_classify_skips_empty_answers(self, mocker):
        """Пустые ответы пропускаются."""
        client = RaceClient()
        client._logger = MagicMock()

        client._omni.ask = lambda text: ""
        client._lmstudio.ask = lambda text: "   "

        assert client.classify("что-то") is None

    def test_classify_does_not_log_history(self, mocker):
        """Классификация не пишет в историю LLM."""
        client = RaceClient()
        client._logger = MagicMock()

        client._omni.ask = lambda text: "volumeup"
        client._lmstudio.ask = lambda text: None

        assert client.classify("громче") == "volumeup"
        client._logger.log_llm.assert_not_called()

    def test_classify_announces_providers(self, mocker):
        """Классификация анонсирует участников гонки."""
        client = RaceClient()
        mock_output = MagicMock()
        client._set_output(mock_output)
        client._logger = MagicMock()

        client._omni.ask = lambda text: "volumeup"
        client._lmstudio.ask = lambda text: None

        client.classify("громче")

        info_calls = [c.args[0] for c in mock_output.print_info.call_args_list]
        assert any("[LLM Race] Классификация" in call for call in info_calls)
        assert any("Классифицировал" in call for call in info_calls)

    def test_classify_timeout_returns_none(self):
        """Никто не ответил за таймаут — возвращается None."""
        import time

        client = RaceClient()
        client._logger = MagicMock()

        client._omni.ask = lambda text: self._block_forever()
        client._lmstudio.ask = lambda text: self._block_forever()

        start = time.monotonic()
        assert client.classify("что-то", timeout=0.05) is None
        assert time.monotonic() - start < 5
