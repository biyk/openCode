"""тесты lib/telegram/offers.py — кнопки предложения/завершения и разбор нажатий."""

from unittest.mock import MagicMock

from lib.telegram.offers import (
    FINISH_LABEL, FINISH_PREFIX, OfferStore, TaskOffers)


def _config(allowed=(111,)):
    config = MagicMock()
    config.chat_ids = frozenset(str(c) for c in allowed)
    config.allows.side_effect = lambda cid: str(cid) in config.chat_ids
    return config


class TestOfferStore:
    def test_token_maps_back_to_title(self):
        store = OfferStore()
        token = store.register("Уборка")
        assert store.title(token) == "Уборка"

    def test_markup_one_button_per_title(self):
        store = OfferStore()
        markup = store.markup(["А", "Б"])
        rows = markup["inline_keyboard"]
        assert [r[0]["text"] for r in rows] == ["А", "Б"]
        # каждый токен восстанавливается в заголовок
        assert [store.title(r[0]["callback_data"]) for r in rows] == ["А", "Б"]

    def test_old_tokens_are_evicted(self):
        store = OfferStore()
        first = store.register("первая")
        for i in range(200):
            store.register(f"задача{i}")
        assert store.title(first) is None

    def test_finish_token_uses_own_prefix(self):
        """Кнопка «Завершить» не может столкнуться с «Начать» по номеру."""
        store = OfferStore()
        start = store.register("Уборка")
        fin = store.finish_markup("Уборка")["inline_keyboard"][0][0]
        assert start.startswith("t") and fin["callback_data"].startswith(
            FINISH_PREFIX)
        assert fin["text"] == FINISH_LABEL
        assert store.title(fin["callback_data"]) == "Уборка"


class TestTaskOffersSend:
    def test_sends_markup_to_every_chat(self):
        api = MagicMock()
        offers = TaskOffers(api, _config(allowed=(111, 222)))
        offers.offer("Чем занять?", ["А", "Б"])
        assert api.send_message.call_count == 2
        kwargs = api.send_message.call_args.kwargs
        assert "inline_keyboard" in kwargs["reply_markup"]

    def test_empty_titles_sends_plain_text(self):
        api = MagicMock()
        offers = TaskOffers(api, _config())
        offers.offer("вопрос", [])
        assert api.send_message.call_args.kwargs == {}


class TestTaskOffersCallback:
    def _cb(self, data, chat_id=111):
        return {"id": "c1", "data": data, "message": {"chat": {"id": chat_id}}}

    def test_pick_starts_task_and_replies(self):
        api = MagicMock()
        replies = []
        offers = TaskOffers(api, _config(), on_pick=lambda t: f"старт {t}",
                            reply=replies.append,
                            set_chat=lambda c: None)
        token = offers._store.register("Уборка")
        assert offers.handle_callback(self._cb(token)) == token
        api.answer_callback.assert_called_once_with("c1", "старт Уборка")
        assert replies == ["старт Уборка"]

    def test_unknown_chat_is_ignored(self):
        api = MagicMock()
        picked = []
        offers = TaskOffers(api, _config(allowed=(111,)),
                            on_pick=picked.append)
        token = offers._store.register("Уборка")
        assert offers.handle_callback(self._cb(token, chat_id=999)) is None
        assert picked == []
        api.answer_callback.assert_not_called()

    def test_forgotten_token_answers_without_pick(self):
        api = MagicMock()
        picked = []
        offers = TaskOffers(api, _config(), on_pick=picked.append)
        assert offers.handle_callback(self._cb("t999")) == "t999"
        assert picked == []
        api.answer_callback.assert_called_once_with("c1", "")

    def test_pick_failure_does_not_break(self, mocker):
        import lib.telegram.offers as offers_mod
        mocker.patch.object(offers_mod, "swallowed")
        api = MagicMock()
        offers = TaskOffers(api, _config(), on_pick=lambda t: 1 / 0)
        token = offers._store.register("Уборка")
        assert offers.handle_callback(self._cb(token)) == token
        offers_mod.swallowed.assert_called_once()

    def test_pick_tuple_reply_attaches_finish_button(self):
        """Старт с finish_title → ответ уходит с inline-клавиатурой «Завершить»."""
        api = MagicMock()
        calls = []

        def reply(text, markup=None):
            calls.append((text, markup))

        offers = TaskOffers(
            api, _config(),
            on_pick=lambda t: (f"▶️ {t}", t),
            reply=reply, set_chat=lambda c: None)
        token = offers._store.register("Уборка")
        assert offers.handle_callback(self._cb(token)) == token
        text, markup = calls[-1]
        assert text == "▶️ Уборка"
        button = markup["inline_keyboard"][0][0]
        assert button["text"] == FINISH_LABEL
        assert button["callback_data"].startswith(FINISH_PREFIX)
        # токен кнопки завершает ту же задачу
        assert offers._store.title(button["callback_data"]) == "Уборка"

    def test_pick_plain_string_reply_has_no_markup(self):
        """Обратная совместимость: on_pick вернул строку → reply(text) без markup."""
        api = MagicMock()
        calls = []
        offers = TaskOffers(api, _config(),
                            on_pick=lambda t: f"старт {t}",
                            reply=lambda text: calls.append(text))
        token = offers._store.register("Уборка")
        offers.handle_callback(self._cb(token))
        assert calls == ["старт Уборка"]

    def test_finish_callback_invokes_on_finish(self):
        api = MagicMock()
        replies = []
        offers = TaskOffers(api, _config(),
                            on_finish=lambda t: f"⏹ {t}",
                            reply=replies.append,
                            set_chat=lambda c: None)
        token = offers._store.register("Уборка", prefix=FINISH_PREFIX)
        assert offers.handle_callback(self._cb(token)) == token
        api.answer_callback.assert_called_once_with("c1", "⏹ Уборка")
        assert replies == ["⏹ Уборка"]

    def test_finish_unknown_chat_ignored(self):
        api = MagicMock()
        done = []
        offers = TaskOffers(api, _config(allowed=(111,)),
                            on_finish=done.append)
        token = offers._store.register("Уборка", prefix=FINISH_PREFIX)
        assert offers.handle_callback(self._cb(token, chat_id=999)) is None
        assert done == []

    def test_finish_without_on_finish_is_silent(self):
        api = MagicMock()
        replies = []
        offers = TaskOffers(api, _config(), reply=replies.append,
                            set_chat=lambda c: None)
        token = offers._store.register("Уборка", prefix=FINISH_PREFIX)
        assert offers.handle_callback(self._cb(token)) == token
        api.answer_callback.assert_called_once_with("c1", "")
        assert replies == []

    def test_finish_exception_does_not_break(self, mocker):
        import lib.telegram.offers as offers_mod
        mocker.patch.object(offers_mod, "swallowed")
        api = MagicMock()
        offers = TaskOffers(api, _config(), on_finish=lambda t: 1 / 0)
        token = offers._store.register("Уборка", prefix=FINISH_PREFIX)
        assert offers.handle_callback(self._cb(token)) == token
        offers_mod.swallowed.assert_called_once()
