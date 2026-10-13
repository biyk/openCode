"""тесты TaskOffers.recall: просроченный вопрос убирается из чатов.

Ответ не пришёл — в чате висит реплика с кнопками, и по ней хочется ответить
там, где ответа уже никто не ждёт (§4.7). Здесь — память id сообщения вопроса
и её снятие; сама отправка кнопок в test_offers.py.
"""

from unittest.mock import MagicMock

from lib.telegram.offers import TaskOffers


def _config(allowed=(111,)):
    config = MagicMock()
    config.chat_ids = frozenset(str(c) for c in allowed)
    config.allows.side_effect = lambda cid: str(cid) in config.chat_ids
    return config


def _offers(api):
    return TaskOffers(api, _config(allowed=(111, 222)))


def _api(ids):
    api = MagicMock()
    api.send_message.side_effect = list(ids)
    return api


class TestQuestionMemory:
    """Что помнит наблюдатель снятия: id отправленного вопроса, по чатам."""

    def test_offer_remembers_message_ids(self):
        offers = _offers(_api([11, 12]))
        offers.offer("вопрос", ["А", "Б"])
        assert offers._asked == [("111", 11), ("222", 12)]

    def test_not_sent_question_is_not_remembered(self):
        """None от API (сообщение не ушло) — удалять нечем и нечего."""
        api = MagicMock()
        api.send_message.return_value = None
        offers = _offers(api)
        offers.offer("вопрос", [])
        assert offers._asked == []
        assert offers.recall() == 0
        api.delete_message.assert_not_called()

    def test_new_question_forgets_old_ids(self):
        """Снятие касается только висящего вопроса, а не всей истории."""
        offers = _offers(_api([11, 12, 21, 22]))
        offers.offer("первый", [])
        offers.offer("второй", [])
        assert offers._asked == [("111", 21), ("222", 22)]


class TestRecall:
    """Снятие вопроса из чата и его последствия."""

    def test_recall_deletes_every_chat(self):
        api = _api([11, 12])
        offers = _offers(api)
        offers.offer("Чем ты сейчас занимаешься?", ["А"])
        assert offers.recall() == 2
        got = [(c.args[0], c.args[1]) for c in api.delete_message.call_args_list]
        assert got == [("111", 11), ("222", 12)]

    def test_recall_is_single_shot(self):
        """Повтор на пустую память ничего не удаляет (и не дёргает API)."""
        api = _api([11, 12])
        offers = _offers(api)
        offers.offer("вопрос", [])
        offers.recall()
        api.delete_message.reset_mock()
        assert offers.recall() == 0
        api.delete_message.assert_not_called()

    def test_refused_delete_still_forgets(self):
        """Отказ Telegram (нет прав/сообщение древнее) не превращает снимание в цикл."""
        api = _api([11, 12])
        offers = _offers(api)
        offers.offer("вопрос", [])
        api.delete_message.return_value = False
        assert offers.recall() == 0
        assert offers._asked == []

    def test_button_press_does_not_recall(self):
        """Нажатие кнопки — не ответ голосом: вопрос ещё живёт и снимется позже."""
        api = _api([11, 12])
        offers = TaskOffers(api, _config(allowed=(111,)),
                            on_pick=lambda t: f"▶️ {t}",
                            reply=lambda text: None, set_chat=lambda c: None)
        offers.offer("вопрос", ["А"])
        offers.handle_callback({"id": "c1", "data": "t1",
                                "message": {"chat": {"id": 111}}})
        assert offers.recall() == 1
