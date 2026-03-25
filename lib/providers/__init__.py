from abc import ABC, abstractmethod
from typing import Optional


class BaseLLMClient(ABC):
    """Базовый класс для LLM провайдеров."""

    @abstractmethod
    def ask(self, text: str) -> Optional[str]:
        """Отправляет текст в LLM и возвращает ответ."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Возвращает название провайдера."""
        pass


from lib.providers.manager import ProviderManager

__all__ = ["BaseLLMClient", "ProviderManager"]
