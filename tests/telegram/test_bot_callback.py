"""тесты маршрутизации callback_query/offer в TelegramBot (lib/telegram/bot.py).

Бот — только транспорт: нажатие кнопки уходит в TaskOffers, а не в пайплайн
текстовых команд; `offer`/`finish_markup` делегируют сборку клавиатуры туда же.
`broadcast` принимает reply_markup (для оповещения о переработке — кнопка
«Завершить» под текстом), крепится только на последнюю часть длинного текста.
"""

from unittest.mock import MagicMock

from lib.telegram.bot import TelegramBot
from lib.telegram.config import TelegramConfig

CHAT = 111


def _config(**kwargs):
    defaults = dict(token="t", chat_ids=frozenset({str(CHAT)}))
    defaults.update(kwargs)
    return TelegramConfig(**defaults)


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


class TestFinishMarkup:
    """Bot.finish_markup — тонкий прокси к TaskOffers (для broadcast-оповещения)."""

    def test_delegates_to_offers(self):
        bot = _bot()
        bot._offers = MagicMock()
        bot._offers.finish_markup.return_value = {"inline_keyboard": [[]]}
        assert bot.finish_markup("Задача") == {"inline_keyboard": [[]]}
        bot._offers.finish_markup.assert_called_once_with("Задача")


class TestRecallProxy:
    """bot.recall — то же, что TaskOffers.recall: снять вопрос из чата."""

    def test_delegates_to_offers(self):
        bot = _bot()
        bot._offers = MagicMock()
        bot._offers.recall.return_value = 2
        assert bot.recall() == 2
        bot._offers.recall.assert_called_once_with()

    def test_offer_then_recall_round_trip(self):
        """Настоящий TaskOffers за ботом: id вопроса помнятся и снимаются."""
        api = MagicMock()
        api.send_message.side_effect = [41]
        bot = TelegramBot(api, _config(), MagicMock())
        bot.offer("Чем ты сейчас занимаешься?", ["А"])
        assert bot.recall() == 1
        assert api.delete_message.call_args.args == (str(CHAT), 41)


class TestBroadcastMarkup:
    """reply_markup broadcast'а доезжает только до последней части сообщения."""

    def test_last_chunk_only(self):
        api = MagicMock()
        button = {"text": "Завершить", "callback_data": "f1"}
        markup = {"inline_keyboard": [[button]]}
        bot = TelegramBot(api, _config(max_len=4), MagicMock())
        bot.broadcast("abcd\nefgh", reply_markup=markup)
        calls = api.send_message.call_args_list
        assert [c.kwargs.get("reply_markup") for c in calls] == [None, markup]

    def test_no_markup_is_plain_text(self):
        api = MagicMock()
        bot = TelegramBot(api, _config(max_len=4096), MagicMock())
        bot.broadcast("Просто текст")
        call = api.send_message.call_args_list[0]
        assert call.kwargs.get("reply_markup") is None
