# TOOLTIP: TelegramBot: daemon-поток long polling'а, whitelist чатов, ответы в чат
"""Фоновый канал текста из Telegram в пайплайн (long polling daemon-потоком).

Обработка сериализована: `process_text` под замком оркестратора, поэтому
сообщение чата не перемешивается со строкой микрофона (§10). Сборку бота
и решение стартовать вынесли в `lib/telegram/launch.py`. Пишут только чаты
из whitelist — бот запускает shell-команды; неизвестный чат логируется со
своим id (его и добавляем в `telegram.allowed_chat_ids`).
"""

import threading
from typing import Any, Callable, Optional

from lib.core.errors import swallowed
from lib.monitor import registry
from lib.telegram.config import TelegramConfig
from lib.telegram.message import muted, split_chunks
from lib.telegram.offers import TaskOffers

# Подсказка на служебные /команды: в чате их печатают чаще, чем команды.
HELP_TEXT = ("Команды пишите как речь: «громче», «включи ютуб», "
             "«напомни в 18:00 позвонить». Кодовое слово не нужно.")


class TelegramBot:
    """Один поток polling: принимает команды из разрешённых чатов, отвечает."""

    def __init__(self, api: Any, config: TelegramConfig,
                 on_text: Callable[[str, Callable[[str], None]], None],
                 output: Any = None,
                 on_pick: Optional[Callable[[str], Any]] = None,
                 on_finish: Optional[Callable[[str], str]] = None,
                 mute: Optional[Callable[[], bool]] = None) -> None:
        self._api = api
        self._config = config
        self._on_text = on_text
        self._output = output
        self._mute = mute
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._offset = 0
        self._chat_id: Optional[str] = None
        self._unknown: set[str] = set()
        self._offers = TaskOffers(api, config, on_pick=on_pick,
                                  on_finish=on_finish,
                                  reply=self.reply, set_chat=self._remember)

    # ---------- Поток ----------

    def start(self) -> None:
        """Запускает daemon-поток polling (повторный вызов — no-op)."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="telegram-poll")
        self._thread.start()

    def stop(self) -> None:
        """Останавливает поток и ждёт, пока текущий polling-запрос отвалится."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            registry.report("telegram", "Telegram-бот", registry.WORKING,
                            "long polling")
            try:
                handled = self.poll_once()
            except Exception as error:            # цикл не должен умирать
                swallowed("telegram.loop", error)
                handled = None
            if handled is None:                   # сбой сети/API — пауза
                registry.report("telegram", "Telegram-бот", registry.ERROR,
                                f"пауза {self._config.retry_s:.0f}с")
                self._stop.wait(self._config.retry_s)

    # ---------- Один шаг (публично для тестов) ----------

    def poll_once(self) -> Optional[int]:
        """Забирает новые обновления. None — сбой (цикл сделает паузу)."""
        updates = self._api.get_updates(self._offset,
                                        self._config.poll_timeout_s)
        if updates is None:
            return None
        commands = 0
        for update in updates:
            self._advance(update)
            if self.handle(update) is not None:
                commands += 1
        return commands

    def _advance(self, update: dict) -> None:
        """Сдвигает offset: полученные обновления Telegram больше не вернёт."""
        uid = update.get("update_id")
        if isinstance(uid, int):
            self._offset = max(self._offset, uid + 1)

    def handle(self, update: dict) -> Optional[str]:
        """Отдаёт текст/нажатие разрешённого чата в пайплайн; None — не команда."""
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            return self._offers.handle_callback(callback)
        message = update.get("message")
        if not isinstance(message, dict):
            return None
        chat = message.get("chat")
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        text = str(message.get("text") or "").strip()
        if not text or chat_id is None:
            return None
        if not self._config.allows(chat_id):
            self._warn_unknown(chat_id)
            return None
        self._chat_id = str(chat_id)
        if text.startswith("/"):
            self.reply(HELP_TEXT)                 # /start — подсказка, не команда
            return None
        try:
            self._on_text(text, self.reply)
        except Exception as error:                # команда не роняет polling
            swallowed("telegram.on_text", error)
        return text

    def _warn_unknown(self, chat_id: Any) -> None:
        """Один раз на чат: напоминание, что whitelist нужно пополнить."""
        key = str(chat_id)
        if key in self._unknown:
            return
        self._unknown.add(key)
        self._print(f"[Telegram] Чат {key} не в whitelist — добавьте его в "
                    f"telegram.allowed_chat_ids")

    # ---------- Ответы ----------

    def _remember(self, chat_id: str) -> None:
        """Запоминает чат ответа (нажатие кнопки приходит без пред. сообщения)."""
        self._chat_id = chat_id

    def offer(self, text: str, titles: list) -> None:
        """Инициативный вопрос с кнопками выбора задачи во все чаты whitelist."""
        if muted(self._mute, "предложение", self._print):
            return
        self._offers.offer(text, titles)

    def recall(self) -> int:
        """Снимает сообщение последнего вопроса: ответа нет — кнопок тоже нет."""
        return self._offers.recall()

    def finish_markup(self, title: str) -> dict:
        """Одна кнопка «Завершить» (для broadcast-оповещения о переработке)."""
        return self._offers.finish_markup(title)

    def reply(self, text: str, reply_markup: Optional[dict] = None) -> None:
        """Ответ в чат команды; при разбиении на части markup — на последней части."""
        if self._chat_id is None:
            self._print("[Telegram] Отвечать некуда: чат ещё не писал боту")
            return
        parts = self.chunks(text)
        for idx, chunk in enumerate(parts):
            markup = reply_markup if idx == len(parts) - 1 else None
            if not self._api.send_message(self._chat_id, chunk,
                                          reply_markup=markup):
                self._print("[Telegram] Ответ не отправлен (ошибка в логе)")

    def broadcast(self, text: str, reply_markup: Optional[dict] = None) -> None:
        """Инициативное уведомление во все чаты whitelist (оповещение).

        Ответы на сообщения пользователя (`reply`) здесь не проходят: сон их
        не снимает — в чате можно оставаться на связи и ночью.
        """
        if muted(self._mute, "уведомление", self._print):
            return
        for chat_id in sorted(self._config.chat_ids):
            parts = self.chunks(text)
            for idx, chunk in enumerate(parts):
                m = reply_markup if idx == len(parts) - 1 else None
                if not self._api.send_message(chat_id, chunk, reply_markup=m):
                    self._print("[Telegram] Уведомление не отправлено "
                                "(ошибка в логе)")

    def chunks(self, text: str) -> list[str]:
        """Режет ответ по telegram.max_len (реализация — telegram/message.py)."""
        return split_chunks(str(text), int(self._config.max_len))

    # ---------- Вывод ----------

    def _print(self, message: str) -> None:
        if self._output is not None:
            self._output.print_info(message)
        else:
            print(message)


__all__ = ["TelegramBot", "HELP_TEXT"]
