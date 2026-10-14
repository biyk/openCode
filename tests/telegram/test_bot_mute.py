# TOOLTIP: Тесты гейта «СОН» в Telegram-боте: инициатива снята, ответы нет
"""Тесты `mute` у TelegramBot (lib/telegram/bot.py).

Правило §4.3: пока идёт мероприятие «СОН», бот не шлёт инициативу —
оповещения (broadcast) и вопросы с кнопками (offer). Ответ на сообщение
пользователя (`reply`) остаётся: иначе ночная команда в чате пропала бы молча.
"""

from unittest.mock import MagicMock

from lib.telegram.bot import TelegramBot
from lib.telegram.config import TelegramConfig

CHAT = 111


def _config() -> TelegramConfig:
    return TelegramConfig(token="t", chat_ids=frozenset({str(CHAT)}))


def _bot(api=None, mute=None) -> TelegramBot:
    return TelegramBot(api or MagicMock(), _config(), MagicMock(),
                       output=MagicMock(), mute=mute)


def _message(text="громче", update_id=1) -> dict:
    return {"update_id": update_id,
            "message": {"chat": {"id": CHAT}, "text": text}}


class TestProactiveMuted:
    def test_broadcast_skipped_while_sleeping(self):
        api = MagicMock()
        _bot(api=api, mute=lambda: True).broadcast("Всё ли в порядке?")
        api.send_message.assert_not_called()

    def test_offer_skipped_while_sleeping(self):
        bot = _bot(mute=lambda: True)
        bot._offers = MagicMock()
        bot.offer("Чем ты сейчас занимаешься?", ["Уборка"])
        bot._offers.offer.assert_not_called()

    def test_awake_sends_both(self):
        api = MagicMock()
        bot = _bot(api=api, mute=lambda: False)
        bot._offers = MagicMock()
        bot.broadcast("Всё ли в порядке?")
        bot.offer("Чем занимаешься?", ["Уборка"])
        api.send_message.assert_called_once()
        bot._offers.offer.assert_called_once()

    def test_without_gate_behaves_as_before(self):
        api = MagicMock()
        _bot(api=api).broadcast("текст")
        api.send_message.assert_called_once()

    def test_mute_reason_is_logged(self):
        """Видно, что уведомление не потерялось, а снято по «СОН»."""
        bot = _bot(mute=lambda: True)
        bot.broadcast("текст")
        logged = bot._output.print_info.call_args.args[0]
        assert "СОН" in logged and "уведомление" in logged


class TestReplyNotMuted:
    """Ответ — не инициатива: сон его не снимает, чат остаётся рабочим."""

    def test_reply_goes_out_while_sleeping(self):
        api = MagicMock()
        bot = _bot(api=api, mute=lambda: True)
        bot.handle(_message())
        bot.reply("Выполнено: volumeup")
        assert api.send_message.call_args.args[1] == "Выполнено: volumeup"

    def test_gate_failure_does_not_mute_channel(self):
        """Падение читалки вердикта — канал жив (гейт не цены доставке)."""
        api = MagicMock()

        def boom() -> bool:
            raise OSError("нет токена")

        _bot(api=api, mute=boom).broadcast("текст")
        api.send_message.assert_called_once()
