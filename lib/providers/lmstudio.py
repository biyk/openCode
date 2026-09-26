import requests
from typing import Optional
from pathlib import Path

from lib.core.logger import Logger
from lib.providers import BaseLLMClient

SYSTEM_PROMPT = Path("prompts/chat_template.txt").read_text()


class LmStudioClient(BaseLLMClient):
    """Клиент для локального LM Studio (OpenAI-совместимый API).

    Отправляет запросы в http://localhost:1234/v1/chat/completions.
    """

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None,
                 history_limit: int = 10, timeout: int = 300, log_history: bool = True,
                 announce: bool = True):
        self._base_url = (base_url or "http://localhost:1234/v1").rstrip("/")
        self._model = model or "liquid/lfm2.5-1.2b"
        self._history_limit = history_limit
        self._timeout = timeout
        self._log_history = log_history
        self._announce = announce
        self._logger = Logger()
        self._output = None

    @property
    def name(self) -> str:
        return "LM Studio"

    def _set_output(self, output) -> None:
        """Устанавливает вывод для debug-логирования (вызывается из main)."""
        self._output = output

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
            if self._output:
                if self._announce:
                    self._output.print_info(
                        f"[LLM] {self.name} ({self._model}): запрос"
                    )
                self._output.print_debug(
                    f"[LLM Request] model={self._model}, messages={messages}"
                )
            response = requests.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self._timeout,
            )
            if self._output:
                self._output.print_debug(f"[LLM Status] {response.status_code}")
            response.raise_for_status()
            data = response.json()
            answer = data.get("choices", [{}])[0].get("message", {}).get("content")
            if self._output:
                self._output.print_debug(f"[LLM Response] {answer}")

            if self._log_history:
                self._logger.log_llm("user", text)
            if answer and self._log_history:
                self._logger.log_llm("assistant", answer)

            return answer
        except Exception as e:
            if self._output:
                self._output.print_error(f"[LLM] {self.name}: ошибка: {e}")
                self._output.print_debug(f"[LLM Error] {e}")
            else:
                print(f"[LM Studio] Ошибка: {e}")
            return None
