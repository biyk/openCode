from g4f.client import Client
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

from lib.logger import Logger
from lib.providers import BaseLLMClient

load_dotenv()

SYSTEM_PROMPT = Path("prompts/chat_template.txt").read_text()


class Gpt4FreeClient(BaseLLMClient):
    """Клиент для gpt4free (бесплатные LLM)."""

    def __init__(self, model: str = "gpt-4o-mini", history_limit: int = 10):
        self._model = model
        self._history_limit = history_limit
        self._logger = Logger()
        self._client = Client()

    @property
    def name(self) -> str:
        return "GPT4Free"

    def ask(self, text: str) -> Optional[str]:
        """Отправляет текст в LLM и возвращает ответ."""
        history = self._logger.get_llm_history(self._history_limit)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": text})

        try:
            print(f"[GPT4Free] Отправка запроса...")
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                web_search=False
            )
            answer = response.choices[0].message.content
            print(f"[GPT4Free] Ответ получен")

            self._logger.log_llm("user", text)
            if answer:
                self._logger.log_llm("assistant", answer)

            return answer
        except Exception as e:
            print(f"[GPT4Free] Ошибка: {e}")
            return None
