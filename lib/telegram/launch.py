# TOOLTIP: Фабрика Telegram-бота: секция telegram → TelegramBot, отказ без токена/whitelist
"""Сборка и запуск Telegram-бота по секции `telegram` commands.json.

Отдельно от `lib/telegram/bot.py` (там только цикл polling) — чтобы оба файла
оставались в лимите 200 строк (§9) и чтобы транспорт и решение «поднимать ли
бота» проверялись тестами независимо.

Решение стартовать — безопасное по умолчанию: без токена или без whitelist
бот не запускается вовсе, потому что он исполняет команды на компьютере.
"""

from typing import Any, Optional

from lib.core.tuning import TELEGRAM_VERIFY_S
from lib.telegram.api import TelegramApi
from lib.telegram.bot import TelegramBot
from lib.telegram.config import build_config, missing_parts
from lib.stt.text_inputs import submit_manual_text


def proxy_label(proxy: str) -> str:
    """Прокси для лога без логина/пароля (scheme://host:port)."""
    scheme, _, rest = proxy.partition("://")
    return f"{scheme}://{rest.rsplit('@', 1)[-1]}" if "//" in proxy else proxy


def start_telegram(worker: Any, output: Any) -> Optional[TelegramBot]:
    """Собирает и запускает бота по секции `telegram` commands.json.

    Ключи секции: enabled, token_env, allowed_chat_ids, proxy,
    poll_timeout_s, retry_s, max_len; чего нет — берём из lib.core.tuning.
    Токен берётся из окружения (.env), а не из JSON. None — секция выключена
    или не настроена (без токена и whitelist бот не поднимается: он исполняет
    команды на ПК).
    """
    raw = worker._matcher.get_telegram_config()
    if not raw.get("enabled"):
        return None
    config = build_config(raw)
    problems = missing_parts(config)
    if problems:
        output.print_error(
            "[Telegram] Бот не запущен: " + "; ".join(problems))
        return None
    api = TelegramApi(config.token, proxy=config.proxy)
    name = api.get_me(timeout_s=TELEGRAM_VERIFY_S) or "?"
    bot = TelegramBot(api, config, output=output,
                      on_text=lambda text, sink: submit_manual_text(
                          worker, text, reply=sink))
    bot.start()
    via = (f" через прокси {proxy_label(config.proxy)}"
           if config.proxy else "")
    output.print_info(
        f"[Telegram] @{name}: команды из чатов "
        f"{', '.join(sorted(config.chat_ids))}, ответы текстом{via}")
    return bot


__all__ = ["start_telegram", "proxy_label"]
