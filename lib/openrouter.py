import os
import requests
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class OpenRouterClient:
    """Клиент для отправки запросов в OpenRouter LLM."""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self._base_url = "https://openrouter.ai/api/v1/chat/completions"

    def ask(self, text: str) -> Optional[str]:
        """Отправляет текст в LLM и возвращает ответ."""
        if not self._api_key:
            print("[OpenRouter] API ключ не найден")
            return None

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://voice-control.local",
            "X-Title": "VoiceControl",
        }

        payload = {
            "model": "openrouter/free",
            "messages": [
                {
                    "role": "user",
                    "content": text
                }
            ]
        }

        try:
            print(f"[OpenRouter] Отправка запроса...")
            response = requests.post(
                self._base_url,
                headers=headers,
                json=payload,
                timeout=30
            )
            print(f"[OpenRouter] Статус: {response.status_code}")
            #print(f"[OpenRouter] Ответ: {response.text[:500]}")
            response.raise_for_status()
            data = response.json()
            print(f"[OpenRouter] Ответ получен")
            return data.get("choices", [{}])[0].get("message", {}).get("content")
        except Exception as e:
            print(f"[OpenRouter] Ошибка: {e}")
            return None
