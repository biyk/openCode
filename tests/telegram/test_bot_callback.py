"""тесты маршрутизации callback_query/offer в TelegramBot (lib/telegram/bot.py).

Бот — только транспорт: нажатие кнопки уходит в TaskOffers, а не в пайплайн
текстовых команд; `offer` делегирует сборку клавиатуры туда же.
"""

from unittest.mock import MagicMock

from lib.telegram.bot import TelegramBot
from lib.telegram.config import TelegramConfig

CHAT = 111


def _config():
    return TelegramConfig(token="t", chat_ids=frozenset({str(CHAT)}))


def _bot(api=None):
    return TelegramBot(api or MagicMock(), _config(), MagicMock())


class TestCallbackRouting:
    def _cb_update(self):
        return {"update_id": 3,
                "callback_query": {"id": "c1", "data": "t1",
                                   "message": {"chat": {"id": CHAT}}}}

    def test_callback_goes_to_offers(self):
        on_text = MagicMock()
        bot = TelegramBot(MagicMock(), _config(), on_text)
        bot._offers = MagicMock()
        bot._offers.handle_callback.return_value = "t1"
        assert bot.handle(self._cb_update()) == "t1"
        bot._offers.handle_callback.assert_called_once()
        on_text.assert_not_called()

    def test_offer_delegates_to_offers(self):
        bot = _bot()
        bot._offers = MagicMock()
        bot.offer("вопрос", ["А", "Б"])
        bot._offers.offer.assert_called_once_with("вопрос", ["А", "Б"])

    def test_remember_sets_reply_chat(self):
        bot = _bot()
        bot._remember("555")
        assert bot._chat_id == "555"
