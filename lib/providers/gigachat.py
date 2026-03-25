import os
import base64
import uuid
import time
import warnings
import requests
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

from lib.logger import Logger
from lib.providers import BaseLLMClient

load_dotenv()

SYSTEM_PROMPT = Path("prompts/chat_template.txt").read_text()


class GigaChatClient(BaseLLMClient):
    """Клиент для общения с GigaChat API."""

    def __init__(self, api_key: Optional[str] = None, client_id: Optional[str] = None,
                 scope: Optional[str] = None, history_limit: int = 10):
        self._api_key = api_key or os.getenv("GIGACHAT_API_KEY")
        self._client_id = client_id or os.getenv("GIGACHAT_CLIENT_ID")
        self._scope = scope or os.getenv("GIGACHAT_API_SCOPE")
        self._history_limit = history_limit
        self._logger = Logger()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    @property
    def name(self) -> str:
        return "GigaChat"

    def _get_access_token(self) -> Optional[str]:
        """Получает access token для GigaChat API."""
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        if not self._api_key or not self._client_id:
            print("[GigaChat] API ключ или Client ID не найдены")
            return None

        try:
            decoded = base64.b64decode(self._api_key).decode()
            auth_key = base64.b64encode(decoded.encode()).decode()
        except Exception:
            auth_key = base64.b64encode(self._api_key.encode()).decode()

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {auth_key}",
        }

        payload = {"scope": self._scope}

        try:
            print("[GigaChat] Получение access token...")
            response = requests.post(
                "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                headers=headers,
                data=payload,
                timeout=30,
                verify=False,
            )
            response.raise_for_status()
            data = response.json()
            self._access_token = data.get("access_token")
            expires_in = data.get("expires_in", 1800)
            self._token_expires_at = time.time() + expires_in - 60
            print("[GigaChat] Access token получен")
            return self._access_token
        except Exception as e:
            print(f"[GigaChat] Ошибка получения токена: {e}")
            return None

    def _get_models(self) -> Optional[list]:
        """Получает список доступных моделей."""
        token = self._get_access_token()
        if not token:
            return None

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }

        try:
            response = requests.get(
                "https://gigachat.devices.sberbank.ru/api/v1/models",
                headers=headers,
                timeout=30,
                verify=False,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except Exception as e:
            print(f"[GigaChat] Ошибка получения моделей: {e}")
            return None

    def ask(self, text: str) -> Optional[str]:
        """Отправляет текст в GigaChat и возвращает ответ."""
        token = self._get_access_token()
        if not token:
            return None

        history = self._logger.get_llm_history(self._history_limit)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": text})

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }

        payload = {
            "model": "GigaChat",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 500,
        }

        try:
            print("[GigaChat] Отправка запроса...")
            response = requests.post(
                "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
                verify=False,
            )
            print(f"[GigaChat] Статус: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            answer = data.get("choices", [{}])[0].get("message", {}).get("content")
            print("[GigaChat] Ответ получен")

            self._logger.log_llm("user", text)
            if answer:
                self._logger.log_llm("assistant", answer)

            return answer
        except Exception as e:
            print(f"[GigaChat] Ошибка: {e}")
            return None
