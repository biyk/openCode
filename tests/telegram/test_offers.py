"""тесты lib/telegram/offers.py — кнопки предложения задач и разбор нажатий."""

from unittest.mock import MagicMock

from lib.telegram.offers import OfferStore, TaskOffers


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
