# TOOLTIP: Единый липкий вердикт «идёт СОН» — гейт всех инициативных сообщений
"""Один источник правды о сне: спит пользователь или нет.

Раньше «спим ли» пересчитывали на месте (idle-ветка монитора) из свежего
чтения календаря с откатом «нет событий — значит не спим» (§4.3). Сбой
OAuth/сети посреди ночи превращался в «не спим», и монитор поднимал всё:
озвучку, вопрос и кнопки в Telegram — то есть сыпал уведомлениями в то время,
когда их быть не должно. Теперь вердикт живёт здесь и знает о нём весь код:

- `check_sleeping()` — читает календарь и обновляет кэш (его зовёт фоновый
  опрос статусов через checker `sleep` и каждый цикл `task_monitor`);
- `is_sleeping()` — дешёвое чтение кэша, без сети: его подставляют в гейт
  сообщений (Telegram `mute`, `task_monitor` `sleep_fn`);
- статус `sleeping` (`targets/<host>/status.json`) — то же значение наружу,
  через него команды могут требовать/исключать сон.

Липкость — главное отличие от прежнего fail-open: сбой календаря НЕ меняет
вердикт. Обрыв сети во время сна оставляет сна, а не включает уведомления;
при свежем процессе (вердикт ещё не вычислен) остаётся «не спим» — поведение
как раньше, молчание не включится из-за сломанного календаря.

Сон при запуске НЕ проверяем (решение пользователя): вердикт считает только
цикл уже запущенного приложения — фоновый опрос статуса и такт монитора.
"""

import threading
from datetime import datetime, timedelta
from typing import Any, Optional

from lib.core.errors import swallowed
from lib.monitor import registry
from lib.taskflow.task_schedule import sleep_now

# Имя статуса в status.json и строки в панели «Сервисы».
SLEEP_STATUS = "sleeping"
SLEEP_TITLE = "Сон"

_lock = threading.Lock()
_sleeping = False                 # нет вердикта = не спим (fail-open на старте)
_calendar: Any = None             # ленивый GoogleCalendar (свой OAuth-кэш)


def is_sleeping() -> bool:
    """Кэш вердикта без сети — читают его гейты сообщений."""
    with _lock:
        return _sleeping


def set_sleeping(value: bool) -> None:
    """Выставить вердикт вручную (тесты; в проде пишет check_sleeping)."""
    global _sleeping
    with _lock:
        _sleeping = bool(value)


def calendar() -> Any:
    """Ленивый GoogleCalendar: импорт внутри, чтобы не звать OAuth зря."""
    global _calendar
    if _calendar is None:
        from lib.google_calendar import GoogleCalendar
        _calendar = GoogleCalendar()
    return _calendar


def today_events(gcal: Any = None, now: Optional[datetime] = None) -> list:
    """Сегодняшние события календаря; пустой список при сбое (не «не спим»)."""
    moment = now or datetime.now().astimezone()
    day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        return list((gcal or calendar()).list_events_between(
            day_start, day_start + timedelta(days=1))) or []
    except Exception as error:            # нет токена/сети — липкий вердикт
        return swallowed("sleep_gate.events", error, [])


def check_sleeping(gcal: Any = None, now: Optional[datetime] = None) -> bool:
    """Пересчитать и запомнить «идёт СОН»; сбой календаря — держим прошлый.

    Пустой список событий — тоже сбой (его возвращает `today_events` на
    исключении), поэтому вердикт не пересчитывается: иначе обрыв связи
    молча переключил бы «спим» на «не спим» и уведомления вернулись бы.
    """
    moment = now or datetime.now().astimezone()
    events = today_events(gcal, moment)
    if not events:
        _report(is_sleeping(), "календарь недоступен — держим вердикт")
        return is_sleeping()
    value = sleep_now(events, moment)
    set_sleeping(value)
    _report(value, "уведомления сняты" if value else "опрос календаря")
    return value


def _report(value: bool, detail: str) -> None:
    """Строка «Сон» в панели «Сервисы»: видно, почему молчим."""
    registry.report(SLEEP_STATUS, SLEEP_TITLE,
                    registry.IDLE if value else registry.WORKING,
                    ("идёт «СОН», " if value else "не спим, ") + detail)
