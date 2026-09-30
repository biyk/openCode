# TOOLTIP: Кнопки предложения задач в Telegram: inline-клавиатура и разбор нажатий
"""Отправка вопроса с кнопками и обработка нажатий (callback_query).

Кнопка шлёт короткий `callback_data` (не сам заголовок: у Telegram лимит 64
байта, а названия задач длиннее и на кириллице — в байтах тем более). По
токену нажатия восстанавливаем заголовок и зовём `on_pick` — он запускает
задачу и возвращает текст ответа в чат. Карта токенов зациклена (держим
последние N), чтобы старые предложения не копились.

Транспорт (sendMessage/answerCallbackQuery) и whitelist-решение — на стороне
вызывающего; здесь только сборка клавиатуры, сопоставление нажатия и отправка.
"""

from typing import Any, Callable, Optional

from lib.core.errors import swallowed

# Префикс токена кнопки (короткий: лимит callback_data — 64 байта).
TOKEN_PREFIX = "t"
# Сколько последних кнопок помнить (старше — забываем).
MAX_KEEP = 64
# Лимит длины текста одной кнопки у Telegram.
BUTTON_LABEL_MAX = 64


class OfferStore:
    """Двусторонняя карта «токен кнопки ↔ заголовок задачи» + сборка markup."""

    def __init__(self) -> None:
        self._by_token: dict[str, str] = {}
        self._order: list[str] = []
        self._seq = 0

    def register(self, title: str) -> str:
        """Заводит токен под заголовок; возвращает его для callback_data."""
        self._seq += 1
        token = f"{TOKEN_PREFIX}{self._seq}"
        self._by_token[token] = title
        self._order.append(token)
        while len(self._order) > MAX_KEEP:            # не копить старые
            self._by_token.pop(self._order.pop(0), None)
        return token

    def title(self, token: str) -> Optional[str]:
        """Заголовок по токену нажатия (None — кнопка уже забыта)."""
        return self._by_token.get(token)

    def markup(self, titles: list[str]) -> dict:
        """Inline-клавиатура: по кнопке на задачу, каждая на своей строке."""
        rows = []
        for title in titles:
            token = self.register(title)
            rows.append([{"text": title[:BUTTON_LABEL_MAX],
                          "callback_data": token}])
        return {"inline_keyboard": rows}


class TaskOffers:
    """Шлёт вопрос с кнопками во все чаты whitelist и разбирает нажатия."""

    def __init__(self, api: Any, config: Any,
                 on_pick: Optional[Callable[[str], str]] = None,
                 reply: Optional[Callable[[str], None]] = None,
                 set_chat: Optional[Callable[[str], None]] = None) -> None:
        self._api = api
        self._config = config
        self._on_pick = on_pick
        self._reply = reply
        self._set_chat = set_chat
        self._store = OfferStore()

    def offer(self, text: str, titles: list[str]) -> None:
        """Вопрос с кнопками выбора задачи; без задач — просто текст в чат."""
        clean = [str(t).strip() for t in (titles or []) if str(t).strip()]
        if not clean:
            for chat_id in sorted(self._config.chat_ids):
                self._api.send_message(chat_id, text)
            return
        markup = self._store.markup(clean)
        for chat_id in sorted(self._config.chat_ids):
            self._api.send_message(chat_id, text, reply_markup=markup)

    def handle_callback(self, callback: dict) -> Optional[str]:
        """Нажатие кнопки: запускает задачу, отвечает в чат; None — не наше."""
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        data = str(callback.get("data") or "")
        if chat_id is None or not self._config.allows(chat_id):
            return None                         # чат не в whitelist — молчим
        if self._set_chat is not None:
            self._set_chat(str(chat_id))
        answer = self._pick(self._store.title(data))
        self._api.answer_callback(callback.get("id"), answer)
        if answer and self._reply is not None:
            self._reply(answer)
        return data or None

    def _pick(self, title: Optional[str]) -> str:
        """Запуск выбранной кнопки; текст ответа ('' — молча)."""
        if title is None or self._on_pick is None:
            return ""
        try:
            return str(self._on_pick(title) or "")
        except Exception as error:               # нажатие не роняет polling
            swallowed("telegram.on_pick", error)
            return ""


__all__ = ["OfferStore", "TaskOffers", "TOKEN_PREFIX", "MAX_KEEP",
           "BUTTON_LABEL_MAX"]
