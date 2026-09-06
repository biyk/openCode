import requests
from typing import Optional
from pathlib import Path

from lib.logger import Logger
from lib.providers import BaseLLMClient

SYSTEM_PROMPT = Path("prompts/chat_template.txt").read_text()


class OmniRouterClient(BaseLLMClient):
    """Клиент для локального OmniRouter прокси (OpenAI-совместимый API).

    Отправляет запросы в http://localhost:20128/v1/chat/completions.
    """

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None,
                 history_limit: int = 10, timeout: int = 300):
        self._base_url = (base_url or "http://localhost:20128/v1").rstrip("/")
        self._model = model or "ds-web/deepseek-v4-flash-search"
        self._history_limit = history_limit
        self._timeout = timeout
        self._logger = Logger()

    @property
    def name(self) -> str:
        return "OmniRouter"

    def ask(self, text: str) -> Optional[str]:
        """Отправляет текст в LLM и возвращает ответ."""
        history = self._logger.get_llm_history(self._history_limit)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": text})

        headers = {
            "Content-Type": "application/json",
        }

        payload = {
            "model": self._model,
            "messages": messages,
        }

        try:
            print("[OmniRouter] Отправка запроса...")
            response = requests.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self._timeout,
            )
            print(f"[OmniRouter] Статус: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            answer = data.get("choices", [{}])[0].get("message", {}).get("content")
            print("[OmniRouter] Ответ получен")

            self._logger.log_llm("user", text)
            if answer:
                self._logger.log_llm("assistant", answer)

            return answer
        except Exception as e:
            print(f"[OmniRouter] Ошибка: {e}")
            return None