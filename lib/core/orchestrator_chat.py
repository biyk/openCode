# TOOLTIP: Миксин оркестратора: ответ текстовому источнику (чат) вместо озвучки
"""Канал ответа для не-голосовых источников команд (Telegram).

Команда приходит оттуда, где вслух говорить не нужно: печать в консоль,
сообщение в чат. Если у запроса есть `reply`, оркестратор отправляет текст
источнику и НЕ озвучивает его — динамики молчат, пока пользователь в чате.

Ответы на асинхронные вещи (итог opencode) приходят позже конца `process_text`,
поэтому канал запоминается вместе с запросом (очередь opencode), а не берётся
из текущего запроса.
"""

from typing import Callable, Optional

from lib.core.errors import swallowed

# Префикс подтверждения: пользователь чата должен видеть, что команда принята.
CHAT_DONE_PREFIX = "Выполнено"
# Ни один уровень не распознал фразу — в чате это видно только как молчание.
CHAT_NOT_RECOGNIZED = "Команда не распознана"
# Управление режимом разработки остаётся голосовым (оно про микрофон и TTS).
CHAT_NO_DEV_MODE = "Режим разработки — только голосом"


class OrchestratorChatMixin:
    """Миксин Orchestrator: канал reply и отправка ответов в него."""

    # Канал ответа текущего запроса (None — запрос из микрофона);
    # ставит Orchestrator.__init__, миксини без него работают как раньше.
    _reply: Optional[Callable[[str], None]]

    def _begin_request(self, reply: Optional[Callable[[str], None]]) -> bool:
        """Отмечает источник запроса. True — запрос из чата (не из микрофона)."""
        self._reply = reply
        return reply is not None

    def _chat_active(self) -> bool:
        """True, если текущий запрос пришёл из чата (есть канал ответа)."""
        return getattr(self, "_reply", None) is not None

    def _chat_send(self, sink: Optional[Callable[[str], None]],
                   text: str) -> bool:
        """Отправляет текст конкретному каналу; False — канала нет или пусто.

        Сбой отправки не роняет обработку команды: ошибка логируется,
        пользователь просто не получит этот фрагмент.
        """
        if sink is None or not text or not text.strip():
            return False
        try:
            sink(text)
        except Exception as error:                # чат не должен ронять пайплайн
            return swallowed("chat.reply", error, False)
        return True

    def _chat_reply(self, text: str) -> bool:
        """Отправляет текст источнику текущего запроса (чат либо None)."""
        return self._chat_send(getattr(self, "_reply", None), text)

    def _chat_done(self, cmd_id: str) -> bool:
        """Подтверждает чату выполненную команду (голос её слышит озвучкой)."""
        return self._chat_reply(f"{CHAT_DONE_PREFIX}: {cmd_id}")

    def _chat_not_recognized(self) -> bool:
        """Сообщает чату, что фраза не похожа ни на одну команду."""
        return self._chat_reply(CHAT_NOT_RECOGNIZED)


__all__ = ["OrchestratorChatMixin", "CHAT_DONE_PREFIX", "CHAT_NOT_RECOGNIZED",
           "CHAT_NO_DEV_MODE"]
