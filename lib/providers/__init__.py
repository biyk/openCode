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


from .lmstudio import LmStudioClient  # noqa: E402
from .omni import OmniRouterClient  # noqa: E402
from .race import RaceClient  # noqa: E402

__all__ = ["BaseLLMClient", "LmStudioClient", "OmniRouterClient", "RaceClient"]
