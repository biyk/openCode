# TOOLTIP: Учёт «проглоченных» ошибок: helper swallowed() + подсказка о reauth
"""Хелпер для мест, которые намеренно глотают ошибку, чтобы ассистент жил.

Правило (TODO про blind except): в `except Exception` молчать запрещено —
минимум логируем через `swallowed()`. Функция возвращает default, поэтому
вызов на месте — одна строка: `return swallowed("gcal.delete_event", e, False)`.
"""

import logging
from typing import Any

INFO = logging.INFO
WARNING = logging.WARNING

_log = logging.getLogger("voice.errors")

# Google-авторизация: reauth.py пересоздаёт token.json интерактивным консентом.
AUTH_HINT = "Google-авторизация слетела — выполни: python reauth.py"


def is_auth_error(exc: BaseException) -> bool:
    """Похожа ли ошибка на срыв OAuth (RefreshError / HTTP 401 / 403).

    Проверяем по имени класса и атрибуту resp.status без импорта google:
    ядро не должно зависеть от google-библиотек.
    """
    if type(exc).__name__ == "RefreshError":
        return True
    resp = getattr(exc, "resp", None)
    return getattr(resp, "status", None) in (401, 403)


def swallowed(where: str, exc: BaseException, default: Any = None,
              level: int = WARNING) -> Any:
    """Логирует проглоченную ошибку и возвращает default (употреблять в except).

    where — короткая метка места («gcal.put_done_event»); для auth-ошибок
    к сообщению добавляется подсказка про reauth.py.
    """
    message = f"[Swallowed] {where}: {type(exc).__name__}: {exc}"
    if is_auth_error(exc):
        message += f" ({AUTH_HINT})"
    _log.log(level, message)
    return default
