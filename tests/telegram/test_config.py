"""Тесты конфига Telegram-канала (lib/telegram/config.py).

Токен не хранится в commands.json (файл в git) — только имя переменной
окружения; whitelist чатов обязателен: без него бот не должен стартовать.
"""

import pytest

from lib.core.tuning import TELEGRAM_MAX_LEN, TELEGRAM_POLL_TIMEOUT_S
from lib.telegram.config import (TelegramConfig, build_config, missing_parts,
                                 read_token)


class TestBuildConfig:
    def test_token_and_ids_from_section(self):
        cfg = build_config(
            {"token_env": "MY_BOT_TOKEN", "allowed_chat_ids": [111, "222"]},
            env={"MY_BOT_TOKEN": "T-42"})
        assert cfg.token == "T-42"
        assert cfg.chat_ids == frozenset({"111", "222"})

    def test_ids_may_come_from_env_only(self):
        cfg = build_config({"token_env": "TOK"},
                           env={"TOK": "t", "TELEGRAM_CHAT_IDS": "7;8, 9"})
        assert cfg.chat_ids == frozenset({"7", "8", "9"})

    def test_defaults_from_tuning(self):
        cfg = build_config({"token_env": "TOK"}, env={"TOK": "t"})
        assert cfg.poll_timeout_s == TELEGRAM_POLL_TIMEOUT_S
        assert cfg.max_len == TELEGRAM_MAX_LEN

    def test_section_overrides_timings(self):
        cfg = build_config({"poll_timeout_s": 5, "retry_s": 1, "max_len": 300},
                           env={})
        assert (cfg.poll_timeout_s, cfg.retry_s, cfg.max_len) == (5.0, 1.0, 300)

    def test_proxy_from_section_or_env(self):
        """Прокси нужен там, где до Telegram нет прямого маршрута."""
        cfg = build_config({"proxy": "socks5h://10.0.0.1:1080"}, env={})
        assert cfg.proxy == "socks5h://10.0.0.1:1080"
        cfg = build_config({}, env={"TELEGRAM_PROXY": "http://10.0.0.1:3128"})
        assert cfg.proxy == "http://10.0.0.1:3128"
        assert build_config({}, env={}).proxy == ""

    def test_empty_section_is_disabled_config(self):
        """Пустая секция не роняет сборку: проблемы покажет missing_parts."""
        cfg = build_config({}, env={})
        assert cfg.token == ""
        assert cfg.chat_ids == frozenset()


class TestWhitelist:
    def test_allows_compares_as_strings(self):
        cfg = TelegramConfig(token="t", chat_ids=frozenset({"123"}))
        assert cfg.allows(123) is True          # Telegram присылает числом
        assert cfg.allows("123") is True
        assert cfg.allows(1234) is False

    def test_empty_whitelist_allows_nobody(self):
        assert TelegramConfig(token="t").allows(1) is False


class TestMissingParts:
    def test_ok_config(self):
        cfg = TelegramConfig(token="t", chat_ids=frozenset({"1"}))
        assert missing_parts(cfg) == []

    def test_reports_both_gaps(self):
        problems = missing_parts(TelegramConfig())
        assert len(problems) == 2
        assert any("токен" in p for p in problems)
        assert any("whitelist" in p for p in problems)


class TestReadToken:
    def test_reads_named_variable(self):
        assert read_token({"token_env": "A"}, env={"A": " secret "}) == "secret"

    def test_explicit_env_never_touches_dotenv(self, mocker):
        """env передан — никакого чтения реального окружения и .env."""
        load = mocker.patch("dotenv.load_dotenv")
        assert read_token({"token_env": "A"}, env={}) == ""
        load.assert_not_called()

    def test_falls_back_to_dotenv(self, mocker):
        """Без переменной в реальном окружении пробуем .env."""

        def fake_load(*args, **kwargs):
            import os
            os.environ["TELEGRAM_BOT_TOKEN"] = "from-dotenv"

        mocker.patch.dict("os.environ", {}, clear=True)
        mocker.patch("dotenv.load_dotenv", side_effect=fake_load)
        assert read_token({}) == "from-dotenv"

    def test_no_dotenv_module_means_no_token(self, mocker):
        mocker.patch.dict("os.environ", {}, clear=True)
        mocker.patch.dict("sys.modules", {"dotenv": None})
        assert read_token({}) == ""


@pytest.mark.parametrize("raw,expected", [
    ([1, 2], ["1", "2"]),
    ("5,6", ["5", "6"]),
    (7, ["7"]),
    ([" 8 ", ""], ["8"]),
    (None, []),
])
def test_as_ids_normalizes(raw, expected):
    from lib.telegram.config import _as_ids
    assert _as_ids(raw) == expected
