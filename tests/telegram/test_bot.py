"""Тесты Telegram-бота (lib/telegram/bot.py).

Бот — только транспорт: whitelist чатов, offset long polling'а и отправка
ответов. Распознаванием команд он не занимается (это оркестратор), поэтому
здесь мок API и мок колбэка on_text.
"""

from unittest.mock import MagicMock

import pytest

import lib.telegram.bot as bot_mod
from lib.telegram.bot import HELP_TEXT, TelegramBot
from lib.telegram.config import TelegramConfig

CHAT = 111


def _config(**kwargs) -> TelegramConfig:
    defaults = dict(token="t", chat_ids=frozenset({str(CHAT)}))
    defaults.update(kwargs)
    return TelegramConfig(**defaults)


def _update(text, chat_id=CHAT, update_id=1):
    return {"update_id": update_id,
            "message": {"chat": {"id": chat_id}, "text": text}}


def _bot(api=None, config=None, on_text=None, output=None):
    return TelegramBot(api or MagicMock(), config or _config(),
                       on_text or MagicMock(), output=output)


class TestHandle:
    def test_allowed_chat_goes_to_pipeline(self):
        on_text = MagicMock()
        bot = _bot(on_text=on_text)
        assert bot.handle(_update("громче")) == "громче"
        text, sink = on_text.call_args.args
        assert (text, sink) == ("громче", bot.reply)

    def test_unknown_chat_is_rejected_once_logged(self):
        output = MagicMock()
        on_text = MagicMock()
        bot = _bot(on_text=on_text, output=output)
        assert bot.handle(_update("громче", chat_id=999)) is None
        assert bot.handle(_update("тише", chat_id=999)) is None
        on_text.assert_not_called()
        assert output.print_info.call_count == 1      # не спамим на каждое сообщение

    def test_slash_command_gets_help_only(self):
        on_text = MagicMock()
        api = MagicMock()
        bot = _bot(api=api, on_text=on_text)
        assert bot.handle(_update("/start")) is None
        on_text.assert_not_called()
        assert api.send_message.call_args.args[1] == HELP_TEXT

    @pytest.mark.parametrize("update", [
        {},                                             # не сообщение
        {"message": {"chat": {"id": CHAT}}},            # без текста
        {"message": {"text": "  ", "chat": {"id": CHAT}}},
        {"message": {"text": "команда"}},               # чат не указан
    ])
    def test_noise_is_not_command(self, update):
        on_text = MagicMock()
        assert _bot(on_text=on_text).handle(update) is None

    def test_pipeline_failure_does_not_break_handler(self, mocker):
        mocker.patch.object(bot_mod, "swallowed")
        on_text = MagicMock(side_effect=RuntimeError("boom"))
        assert _bot(on_text=on_text).handle(_update("громче")) == "громче"
        bot_mod.swallowed.assert_called_once()


class TestPollOnce:
    def test_advances_offset_and_counts(self):
        api = MagicMock()
        api.get_updates.return_value = [_update("громче", update_id=7),
                                        _update("тише", update_id=8)]
        bot = _bot(api=api)
        assert bot.poll_once() == 2
        assert bot._offset == 9
        assert api.get_updates.call_args.args[0] == 0

    def test_second_call_uses_new_offset(self):
        api = MagicMock()
        api.get_updates.return_value = []
        bot = _bot(api=api)
        bot.poll_once()
        bot.poll_once()
        assert api.get_updates.call_args_list[-1].args[0] == bot._offset

    def test_api_failure_reports_none(self):
        api = MagicMock()
        api.get_updates.return_value = None
        assert _bot(api=api).poll_once() is None


class TestLoop:
    def test_pause_after_failure(self, mocker):
        """Сбой API — пауза retry_s, а не пустой цикл запросов."""
        bot = _bot(config=_config(retry_s=3.0))
        mocker.patch.object(bot, "poll_once", return_value=None)

        def fake_wait(seconds):
            bot._stop.set()                   # после паузы поток завершится

        wait = mocker.patch.object(bot._stop, "wait", side_effect=fake_wait)
        bot._loop()
        assert wait.call_args.args[0] == 3.0

    def test_thread_starts_and_stops(self, mocker):
        bot = _bot()
        poll = mocker.patch.object(bot, "poll_once", return_value=0)
        bot.start()
        bot.stop()
        assert bot._thread is None
        assert poll.called


class TestReply:
    def test_sends_to_last_allowed_chat(self):
        api = MagicMock()
        bot = _bot(api=api)
        bot.handle(_update("громче"))
        bot.reply("Выполнено: volumeup")
        assert api.send_message.call_args.args == (str(CHAT), "Выполнено: volumeup")

    def test_without_chat_only_warns(self):
        output, api = MagicMock(), MagicMock()
        _bot(api=api, output=output).reply("текст")
        api.send_message.assert_not_called()
        assert output.print_info.called

    def test_send_failure_is_reported(self):
        output, api = MagicMock(), MagicMock()
        api.send_message.return_value = False
        bot = _bot(api=api, output=output)
        bot.handle(_update("громче"))
        bot.reply("текст")
        assert "не отправлен" in output.print_info.call_args.args[0]


class TestBroadcast:
    """Инициативное уведомление (оповещение о переработке) во все чаты."""

    def test_sends_to_every_allowed_chat(self):
        api = MagicMock()
        config = _config(chat_ids=frozenset({"111", "222"}))
        _bot(api=api, config=config).broadcast("Всё ли в порядке?")
        sent = {c.args[0] for c in api.send_message.call_args_list}
        assert sent == {"111", "222"}
        assert all(c.args[1] == "Всё ли в порядке?"
                   for c in api.send_message.call_args_list)

    def test_ignores_whether_user_ever_wrote(self):
        """В отличие от reply, broadcast не зависит от последнего чата."""
        api = MagicMock()
        _bot(api=api).broadcast("текст")            # никто не писал боту
        api.send_message.assert_called_once()

    def test_empty_whitelist_sends_nothing(self):
        api = MagicMock()
        _bot(api=api, config=_config(chat_ids=frozenset())).broadcast("т")
        api.send_message.assert_not_called()

    def test_send_failure_is_reported(self):
        output, api = MagicMock(), MagicMock()
        api.send_message.return_value = False
        _bot(api=api, output=output).broadcast("текст")
        assert "не отправлено" in output.print_info.call_args.args[0]


class TestChunks:
    def test_groups_lines_up_to_limit(self):
        bot = _bot(config=_config(max_len=10))
        assert bot.chunks("ab\ncd\nefghijklmnop") == ["ab\ncd", "efghijklmn",
                                                      "op"]

    def test_empty_text_yields_nothing(self):
        assert _bot().chunks("\n  \n") == []

    def test_long_line_is_sliced_without_loss(self):
        """Строка длиннее лимита режется жёстко, текст не теряется."""
        bot = _bot(config=_config(max_len=10))
        text = "1234567890abcdefghij"
        assert "".join(bot.chunks(text)).replace("\n", "") == text

    def test_short_text_untouched(self):
        assert _bot().chunks("Выполнено: stop") == ["Выполнено: stop"]

    def test_reply_goes_out_in_chunks(self):
        api = MagicMock()
        bot = _bot(api=api, config=_config(max_len=4))
        bot.handle(_update("громче"))
        bot.reply("abcd\nефг")
        assert [c.args[1] for c in api.send_message.call_args_list] == [
            "abcd", "ефг"]
