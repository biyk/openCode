from typing import Optional

import pytest

from lib.providers import BaseLLMClient


class _ConcreteClient(BaseLLMClient):
    """Конкретная реализация базового класса для тестов."""

    def ask(self, text: str) -> Optional[str]:
        return None

    @property
    def name(self) -> str:
        return "test"


class TestBaseLLMClient:
    """Тесты для абстрактного класса BaseLLMClient."""

    def test_ask_passthrough(self):
        """Прямой вызов ask() через базовый класс выполняет pass-тело."""
        client = _ConcreteClient()
        assert BaseLLMClient.ask(client, "hi") is None

    def test_name_passthrough(self):
        """Прямой вызов геттера name выполняет pass-тело."""
        client = _ConcreteClient()
        assert BaseLLMClient.name.fget(client) is None

    def test_abstract_cannot_be_instantiated(self):
        """Абстрактный класс нельзя инстанцировать напрямую."""
        with pytest.raises(TypeError):
            BaseLLMClient()

    def test_concrete_implementation_works(self):
        """Конкретный подкласс реализует ask и name."""
        client = _ConcreteClient()
        assert client.name == "test"
