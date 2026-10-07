# TOOLTIP: Кнопки предложения/завершения задач в Telegram: inline-клавиатура и разбор нажатий
"""Отправка вопроса с кнопками и обработка нажатий (callback_query).

Кнопка шлёт короткий `callback_data` (не сам заголовок: у Telegram лимит 64
байта, а названия задач длиннее и на кириллице — в байтах тем более). По
токену нажатия восстанавливаем заголовок и зовём `on_pick` — он запускает
задачу и возвращает текст ответа в чат. Карта токенов зациклена (держим
последние N), чтобы старые предложения не копились.

Два вида кнопок отличаются только префиксом токена: `t` — «начать задачу»
изIdle-вопроса, `f` — «завершить» (лепится на ответ о старте; нажатие
уходит в `on_finish`). Один OfferStore на оба — так старая кнопка «старт» не
может случайно уехать в finish по тому же номеру.

Транспорт (sendMessage/answerCallbackQuery) и whitelist-решение — на стороне
вызывающего; здесь только сборка клавиатуры, сопоставление нажатия и отправка.
"""

from typing import Any, Callable, Optional

from lib.core.errors import swallowed

# Префикс токена кнопки (короткий: лимит callback_data — 64 байта).
TOKEN_PREFIX = "t"
# Префикс токена кнопки «завершить» — второй вид нажатия в том же чате.
FINISH_PREFIX = "f"
# Надпись на кнопке завершения (в лимит BUTTON_LABEL_MAX).
FINISH_LABEL = "Завершить"
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

    def register(self, title: str, prefix: str = TOKEN_PREFIX) -> str:
        """Заводит токен под заголовок; возвращает его для callback_data."""
        self._seq += 1
        token = f"{prefix}{self._seq}"
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

    def finish_markup(self, title: str) -> dict:
        """Одна кнопка «Завершить» под конкретный заголовок запущенной задачи."""
        token = self.register(title, prefix=FINISH_PREFIX)
        button = {"text": FINISH_LABEL, "callback_data": token}
        return {"inline_keyboard": [[button]]}


class TaskOffers:
    """Шлёт вопрос с кнопками во все чаты whitelist и разбирает нажатия."""

    def __init__(self, api: Any, config: Any,
                 on_pick: Optional[Callable[[str], Any]] = None,
                 reply: Optional[Callable[..., None]] = None,
                 set_chat: Optional[Callable[[str], None]] = None,
                 on_finish: Optional[Callable[[str], str]] = None) -> None:
        self._api = api
        self._config = config
        self._on_pick = on_pick
        self._on_finish = on_finish
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
        """Нажатие кнопки: запускает/завершает задачу, отвечает в чат."""
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        data = str(callback.get("data") or "")
        if chat_id is None or not self._config.allows(chat_id):
            return None                         # чат не в whitelist — молчим
        if self._set_chat is not None:
            self._set_chat(str(chat_id))
        if data.startswith(FINISH_PREFIX):
            return self._handle_finish(callback, data)
        return self._handle_start(callback, data)

    def _handle_start(self, callback: dict, data: str) -> Optional[str]:
        """Кнопка «начать»: pick → текст; при успехе — плюс кнопка «завершить»."""
        text, finish_title = self._pick(self._store.title(data))
        self._api.answer_callback(callback.get("id"), text)
        if text and self._reply is not None:
            if finish_title is not None:
                self._reply(text, self._store.finish_markup(finish_title))
            else:
                self._reply(text)
        return data or None

    def _handle_finish(self, callback: dict, data: str) -> Optional[str]:
        """Кнопка «завершить»: on_finish → текст; кнопки возврата не лепим."""
        text = self._finish(self._store.title(data))
        self._api.answer_callback(callback.get("id"), text)
        if text and self._reply is not None:
            self._reply(text)
        return data or None

    def _pick(self, title: Optional[str]) -> tuple[str, Optional[str]]:
        """Запуск выбранной кнопки; (текст, заголовок_для_завершения | None).

        on_pick может вернуть либо просто строку (без кнопки), либо пару
        `(text, finish_title)` — когда старт состоялся и есть что завершать.
        """
        if title is None or self._on_pick is None:
            return "", None
        try:
            result = self._on_pick(title)
        except Exception as error:               # нажатие не роняет polling
            swallowed("telegram.on_pick", error)
            return "", None
        if isinstance(result, tuple):
            text, finish_title = (list(result) + [None, None])[:2]
            ft = str(finish_title).strip() if finish_title else None
            return str(text or ""), ft
        return str(result or ""), None

    def _finish(self, title: Optional[str]) -> str:
        """Завершение по кнопке; текст ответа ('' — молча)."""
        if title is None or self._on_finish is None:
            return ""
        try:
            return str(self._on_finish(title) or "")
        except Exception as error:               # нажатие не роняет polling
            swallowed("telegram.on_finish", error)
            return ""


__all__ = ["OfferStore", "TaskOffers", "TOKEN_PREFIX", "FINISH_PREFIX",
           "FINISH_LABEL", "MAX_KEEP", "BUTTON_LABEL_MAX"]
