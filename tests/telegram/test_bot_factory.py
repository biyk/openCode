"""Тесты фабрики start_telegram (lib/telegram/launch.py).

Фабрика читает секцию `telegram` из commands.json и решает, поднимать ли бот:
без токена или без whitelist чат-бот, запускающий команды на ПК, стартовать
не должен. Сеть здесь не нужна — TelegramApi и build_config подменены.
"""

from unittest.mock import MagicMock

import lib.telegram.launch as launch_mod
from lib.telegram.bot import TelegramBot
from lib.telegram.config import TelegramConfig
from lib.telegram.launch import start_telegram

CHAT = 111


def _config(**kwargs) -> TelegramConfig:
    defaults = dict(token="t", chat_ids=frozenset({str(CHAT)}))
    defaults.update(kwargs)
    return TelegramConfig(**defaults)


def _worker(section):
    worker = MagicMock()
    worker._matcher.get_telegram_config.return_value = section
    return worker


def _update(text, chat_id=CHAT, update_id=1):
    return {"update_id": update_id,
            "message": {"chat": {"id": chat_id}, "text": text}}


class TestStartTelegram:
    def test_disabled_section(self):
        assert start_telegram(_worker({}), MagicMock()) is None

    def test_missing_token_refuses_to_start(self, mocker):
        output = MagicMock()
        mocker.patch.object(launch_mod, "build_config",
                            return_value=_config(token=""))
        worker = _worker({"enabled": True, "allowed_chat_ids": [CHAT]})
        assert start_telegram(worker, output) is None
        assert "токен" in output.print_error.call_args.args[0]

    def test_empty_whitelist_refuses_to_start(self, mocker):
        output = MagicMock()
        mocker.patch.object(launch_mod, "build_config",
                            return_value=TelegramConfig(token="t"))
        assert start_telegram(_worker({"enabled": True}), output) is None
        assert "whitelist" in output.print_error.call_args.args[0]

    def test_started_bot_polls_and_is_reported(self, mocker):
        """Готовый конфиг: бот поднят, имя бота взято из getMe."""
        api = mocker.patch.object(launch_mod, "TelegramApi").return_value
        api.get_me.return_value = "voice_bot"
        output = MagicMock()
        mocker.patch.object(launch_mod, "build_config", return_value=_config())
        mocker.patch.object(TelegramBot, "start")
        bot = start_telegram(_worker({"enabled": True}), output)
        assert bot is not None
        bot.start.assert_called_once()
        assert "@voice_bot" in output.print_info.call_args.args[0]

    def test_dead_token_still_starts_with_unknown_name(self, mocker):
        """getMe не ответил — старт не отменяем, имя покажем как «?»."""
        api = mocker.patch.object(launch_mod, "TelegramApi").return_value
        api.get_me.return_value = None
        mocker.patch.object(launch_mod, "build_config", return_value=_config())
        mocker.patch.object(TelegramBot, "start")
        assert start_telegram(_worker({"enabled": True}),
                              MagicMock()) is not None

    def test_on_text_routes_through_manual_input(self, mocker):
        """Сообщение чата идёт тем же путём, что печать в консоль."""
        submit = mocker.patch.object(launch_mod, "submit_manual_text")
        api = mocker.patch.object(launch_mod, "TelegramApi").return_value
        api.get_me.return_value = "b"
        mocker.patch.object(launch_mod, "build_config", return_value=_config())
        mocker.patch.object(TelegramBot, "start")
        worker = _worker({"enabled": True})
        bot = start_telegram(worker, MagicMock())
        bot.handle(_update("громче"))
        assert submit.call_args.args[0] is worker
        assert submit.call_args.args[1] == "громче"
        assert submit.call_args.kwargs["reply"] == bot.reply

    def test_proxy_reaches_api_and_log_without_password(self, mocker):
        """Прокси из секции идёт в API; в лог — без логина/пароля."""
        api_cls = mocker.patch.object(launch_mod, "TelegramApi")
        api_cls.return_value.get_me.return_value = "b"
        mocker.patch.object(launch_mod, "build_config", return_value=_config(
            proxy="socks5h://user:pass@10.0.0.1:1080"))
        mocker.patch.object(TelegramBot, "start")
        output = MagicMock()
        start_telegram(_worker({"enabled": True}), output)
        assert api_cls.call_args.kwargs["proxy"] == \
            "socks5h://user:pass@10.0.0.1:1080"
        message = output.print_info.call_args.args[0]
        assert "10.0.0.1:1080" in message
        assert "user:pass" not in message


class TestProxyLabel:
    def test_credentials_are_stripped(self):
        assert launch_mod.proxy_label("socks5h://u:p@10.0.0.1:1080") == \
            "socks5h://10.0.0.1:1080"

    def test_plain_value_passes_through(self):
        assert launch_mod.proxy_label("10.0.0.1:1080") == "10.0.0.1:1080"
