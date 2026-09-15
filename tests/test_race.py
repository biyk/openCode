import threading
from unittest.mock import MagicMock

from lib.providers.race import RaceClient


class TestRaceClient:
    """Тесты для класса RaceClient."""

    def test_name(self):
        """name возвращает название клиента."""
        assert RaceClient().name == "Race(omni+lmstudio)"

    def test_init_creates_both_clients_without_history(self):
        """Оба саб-клиента создаются с log_history=False."""
        client = RaceClient()
        assert client._omni._log_history is False
        assert client._lmstudio._log_history is False

    def test_set_output_propagates_to_subs(self):
        """_set_output передаётся обоим саб-клиентам."""
        client = RaceClient()
        mock_output = MagicMock()
        client._set_output(mock_output)
        assert client._output == mock_output
        assert client._omni._output == mock_output
        assert client._lmstudio._output == mock_output

    def test_ask_returns_first_response(self, mocker):
        """Когда omni отвечает первым, возвращается его ответ."""
        client = RaceClient()

        gate = threading.Event()
        client._lmstudio.ask = lambda text: gate.wait(5) or "медленный"
        client._omni.ask = lambda text: "быстрый"

        result = client.ask("Привет")
        gate.set()
        assert result == "быстрый"

    def test_ask_lmstudio_first(self, mocker):
        """Когда lmstudio отвечает первым, возвращается его ответ."""
        import time

        client = RaceClient()

        client._omni.ask = lambda text: time.sleep(0.1) or "медленный"
        client._lmstudio.ask = lambda text: "локальный"

        result = client.ask("Привет")
        assert result == "локальный"

    def test_ask_waits_for_second_when_first_none(self, mocker):
        """Если первый поток вернул None, берётся ответ второго."""
        client = RaceClient()

        client._omni.ask = lambda text: None
        client._lmstudio.ask = lambda text: "спасение"

        result = client.ask("Привет")
        assert result == "спасение"

    def test_ask_both_none_returns_none(self, mocker):
        """Если оба вернули None, возвращается None."""
        client = RaceClient()

        client._omni.ask = lambda text: None
        client._lmstudio.ask = lambda text: None

        assert client.ask("Привет") is None

    def test_ask_logs_winner(self, mocker):
        """Победивший ответ логируется в историю, запрос тоже."""
        client = RaceClient()
        client._logger = MagicMock()

        client._omni.ask = lambda text: "победитель"
        client._lmstudio.ask = lambda text: None

        result = client.ask("вопрос")

        assert result == "победитель"
        client._logger.log_llm.assert_any_call("user", "вопрос")
        client._logger.log_llm.assert_any_call("assistant", "победитель")

    def test_ask_exception_in_thread_returns_none(self, mocker):
        """Исключение в потоке не ломает гонку и возвращает None при обоих."""
        client = RaceClient()

        client._omni.ask = lambda text: (_ for _ in ()).throw(RuntimeError("boom"))
        client._lmstudio.ask = lambda text: None

        assert client.ask("Привет") is None

    def test_ask_debug_log_winner_label(self, mocker):
        """При победе логируется info с меткой победителя."""
        client = RaceClient()
        mock_output = MagicMock()
        client._set_output(mock_output)
        client._logger = MagicMock()

        client._lmstudio.ask = lambda text: "первый"
        client._omni.ask = lambda text: None

        result = client.ask("Привет")

        assert result == "первый"
        info_calls = [c.args[0] for c in mock_output.print_info.call_args_list]
        assert any("[LLM Race]" in call and "lmstudio" in call for call in info_calls)

    def test_ask_timeout_returns_none(self):
        """При истечении таймаута (ни один не ответил) возвращается None."""
        client = RaceClient(timeout=0.05)
        client._logger = MagicMock()

        client._omni.ask = lambda text: self._block_forever()
        client._lmstudio.ask = lambda text: self._block_forever()

        import time
        start = time.monotonic()
        result = client.ask("Привет")
        elapsed = time.monotonic() - start

        assert result is None
        assert elapsed < 5

    def test_ask_first_none_second_timeout_returns_none(self):
        """Первый ответ None, второй не успел — возвращается None."""
        client = RaceClient(timeout=0.05)
        client._logger = MagicMock()

        client._omni.ask = lambda text: None
        client._lmstudio.ask = lambda text: self._block_forever()

        result = client.ask("Привет")
        assert result is None

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
