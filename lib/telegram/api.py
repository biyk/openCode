# TOOLTIP: Тонкий клиент Bot API Telegram (getUpdates/sendMessage) поверх requests
"""HTTP-клиент Bot API: long polling обновлений и отправка сообщений.

Только два нужных ассистенту вызова, без сторонних библиотек: async-пакеты
не ложатся в синхронный threading-цикл проекта. Ошибки сети/Telegram
не валят поток — `swallowed()` пишет их в лог, вызывающий код получает None
и пробует позже.
"""

import json

import requests
from typing import Any, Optional

from lib.core.errors import swallowed
from lib.core.tuning import TELEGRAM_REQUEST_TIMEOUT_S

API_BASE = "https://api.telegram.org"


class TelegramApi:
    """Клиент одного бота: методы Bot API по токену."""

    def __init__(self, token: str,
                 timeout_s: float = TELEGRAM_REQUEST_TIMEOUT_S,
                 proxy: str = "") -> None:
        self._token = token
        self._timeout = timeout_s
        # Прокси обязателен там, где прямой маршрут до Telegram отсутствует
        # (в этом проекте — socks5 на LAN-хосте, тот же адрес, что у статуса
        # `proxy`). Схема `socks5h` разрешает DNS тоже через прокси.
        self._proxies = {"http": proxy, "https": proxy} if proxy else None

    def _safe(self, error: Exception) -> Exception:
        """Вырезает токен из текста ошибки.

        requests кладёт полный URL в исключение, а URL бота — это и есть
        токен; лог (`logs/*.log`) и консоль не должны его светить.
        """
        text = str(error)
        if self._token and self._token in text:
            return RuntimeError(
                f"{type(error).__name__}: "
                f"{text.replace(self._token, '<token>')}")
        return error

    def _call(self, method: str, params: dict[str, Any]) -> Optional[Any]:
        """Один вызов Bot API; None — ошибка (уже залогирована)."""
        url = f"{API_BASE}/bot{self._token}/{method}"
        try:
            response = requests.post(url, params=params,
                                     timeout=self._timeout,
                                     proxies=self._proxies)
            response.raise_for_status()
            body = response.json()
            if not body.get("ok"):
                # Описание ошибки Telegram поднимаем и ловим тем же except:
                # место проглатывания остаётся единственным.
                raise RuntimeError(body.get("description") or method)
        except Exception as error:                # сеть/Telegram — не роняем бота
            return swallowed(f"telegram.{method}", self._safe(error), None)
        return body.get("result")

    def get_me(self, timeout_s: Optional[float] = None) -> Optional[str]:
        """Имя бота (@name) для лога запуска; None — токен не работает.

        Вызывается из main-потока при старте, поэтому свой (короткий)
        таймаут: без интернета старт ассистента не должен ждать 45 с.
        """
        previous = self._timeout
        if timeout_s is not None:
            self._timeout = float(timeout_s)
        try:
            result = self._call("getMe", {})
        finally:
            self._timeout = previous
        if not isinstance(result, dict):
            return None
        username = result.get("username") or result.get("first_name") or ""
        return str(username) or None

    def get_updates(self, offset: int,
                    timeout_s: float) -> Optional[list[dict]]:
        """Новые обновления (long polling); None — сбой (цикл сделает паузу)."""
        result = self._call("getUpdates", {
            "offset": offset,
            "timeout": timeout_s,
            # Сообщения и нажатия кнопок (inline keyboard): edited/реакции/
            # каналы нам не команды.
            "allowed_updates": json.dumps(["message", "callback_query"]),
        })
        if not isinstance(result, list):
            return None
        return [u for u in result if isinstance(u, dict)]

    def send_message(self, chat_id: Any, text: str,
                     reply_markup: Optional[dict] = None) -> bool:
        """Отправляет текст в чат; True — Telegram принял сообщение.

        `reply_markup` — inline-клавиатура (кнопки предложения задач); без него
        — обычное текстовое сообщение.
        """
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
        if reply_markup is not None:
            params["reply_markup"] = json.dumps(reply_markup,
                                                ensure_ascii=False)
        return self._call("sendMessage", params) is not None

    def answer_callback(self, callback_id: Any, text: str = "") -> bool:
        """Снимает «часики» нажатия кнопки; True — Telegram принял ответ.

        Без ответа на callback_query кнопка висит «задумчивой» у пользователя.
        Без id (сбой разбора обновления) — ничего не делаем.
        """
        if not callback_id:
            return False
        params: dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            params["text"] = text
        return self._call("answerCallbackQuery", params) is not None


__all__ = ["TelegramApi", "API_BASE"]
