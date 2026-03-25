import os
import requests
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

from lib.logger import Logger
from lib.providers import BaseLLMClient

load_dotenv()

SYSTEM_PROMPT = Path("prompts/chat_template.txt").read_text()


class DeepSeekClient(BaseLLMClient):
    """Клиент для отправки запросов в DeepSeek LLM с историей переписки."""

    def __init__(self, api_key: Optional[str] = None, history_limit: int = 10):
        self._api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self._base_url = "https://api.deepseek.com/v1/chat/completions"
        self._history_limit = history_limit
        self._logger = Logger()

    @property
    def name(self) -> str:
        return "DeepSeek"

    def ask(self, text: str) -> Optional[str]:
        """Отправляет текст в LLM и возвращает ответ."""
        if not self._api_key:
            print("[DeepSeek] API ключ не найден")
            return None

        history = self._logger.get_llm_history(self._history_limit)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": text})

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "deepseek-chat",
            "messages": messages
        }

        try:
            print(f"[DeepSeek] Отправка запроса...")
            response = requests.post(
                self._base_url,
                headers=headers,
                json=payload,
                timeout=30
            )
            print(f"[DeepSeek] Статус: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            answer = data.get("choices", [{}])[0].get("message", {}).get("content")
            print(f"[DeepSeek] Ответ получен")

            self._logger.log_llm("user", text)
            if answer:
                self._logger.log_llm("assistant", answer)

            return answer
        except Exception as e:
            print(f"[DeepSeek] Ошибка: {e}")
            return None
