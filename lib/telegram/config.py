# TOOLTIP: Конфиг Telegram-канала: токен из окружения, whitelist чатов
"""Секция `telegram` в commands.json → готовый к работе конфиг бота.

Токен в JSON не живёт (файл в git) — берётся из переменной окружения, имя
задаётся ключом `token_env` (по умолчанию TELEGRAM_BOT_TOKEN); если переменной
нет, пытаемся подтянуть `.env` через python-dotenv.

`allowed_chat_ids` обязателен и не пуст: бот запускает shell-команды на
компьютере, поэтому первый написавший боту не должен попадать в пайплайн.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from lib.core.tuning import (TELEGRAM_MAX_LEN, TELEGRAM_POLL_TIMEOUT_S,
                             TELEGRAM_RETRY_S)

DEFAULT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
# Id чатов можно задать и без JSON: «123456,789012» в .env.
DEFAULT_CHAT_IDS_ENV = "TELEGRAM_CHAT_IDS"
# Прокси тоже можно держать в окружении, а не в commands.json.
DEFAULT_PROXY_ENV = "TELEGRAM_PROXY"


@dataclass(frozen=True)
class TelegramConfig:
    """Параметры одного бота: токен, разрешённые чаты, тайминги polling."""

    token: str = ""
    chat_ids: frozenset[str] = field(default_factory=frozenset)
    poll_timeout_s: float = TELEGRAM_POLL_TIMEOUT_S
    retry_s: float = TELEGRAM_RETRY_S
    max_len: int = TELEGRAM_MAX_LEN
    # SOCKS/HTTP-прокси для Bot API ("socks5h://host:port"); пусто — напрямую.
    proxy: str = ""

    def allows(self, chat_id: Any) -> bool:
        """Разрешён ли чат (Telegram присылает id числом, храним строками)."""
        return str(chat_id) in self.chat_ids


def _as_ids(values: Any) -> list[str]:
    """Нормализует id чатов (список/строка «1,2»/число) в список строк."""
    if isinstance(values, (str, int)):
        values = str(values).replace(";", ",").split(",")
    result: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text:
            result.append(text)
    return result


def read_token(raw: dict, env: Optional[dict[str, str]] = None) -> str:
    """Токен из окружения по имени `token_env`.

    `env` передан (тесты) — читаем только его, без догрузки `.env`;
    `env=None` — реальный процесс: при пустой переменной пробуем `.env`.
    """
    name = str(raw.get("token_env") or DEFAULT_TOKEN_ENV)
    if env is not None:
        return (env.get(name) or "").strip()
    token = (os.environ.get(name) or "").strip()
    if token:
        return token
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except ImportError:                 # dotenv в requirements, но не обязателен
        return ""
    return (os.environ.get(name) or "").strip()


def build_config(raw: dict, env: Optional[dict[str, str]] = None) -> TelegramConfig:
    """Собирает TelegramConfig из секции `telegram` (env — для тестов)."""
    source = os.environ if env is None else env
    ids = _as_ids(raw.get("allowed_chat_ids"))
    ids += _as_ids(source.get(DEFAULT_CHAT_IDS_ENV) or "")
    return TelegramConfig(
        token=read_token(raw, env),
        chat_ids=frozenset(ids),
        poll_timeout_s=float(raw.get("poll_timeout_s", TELEGRAM_POLL_TIMEOUT_S)),
        retry_s=float(raw.get("retry_s", TELEGRAM_RETRY_S)),
        max_len=int(raw.get("max_len", TELEGRAM_MAX_LEN)),
        proxy=str(raw.get("proxy") or source.get(DEFAULT_PROXY_ENV) or "").strip(),
    )


def missing_parts(config: TelegramConfig) -> list[str]:
    """Что не настроено (пусто = конфиг рабочий)."""
    problems: list[str] = []
    if not config.token:
        problems.append(f"токен: {DEFAULT_TOKEN_ENV} не задан (.env)")
    if not config.chat_ids:
        problems.append("whitelist: telegram.allowed_chat_ids пуст")
    return problems


__all__ = ["TelegramConfig", "build_config", "missing_parts", "read_token",
           "DEFAULT_TOKEN_ENV", "DEFAULT_CHAT_IDS_ENV", "DEFAULT_PROXY_ENV"]
