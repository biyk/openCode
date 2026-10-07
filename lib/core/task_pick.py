# TOOLTIP: Запуск задачи по нажатию кнопки Telegram (тот же путь, что ответ вслух)
"""Обработка клика кнопки «начать задачу»: старт по названию + текст в чат.

Кнопки предложения (`task_monitor` → `telegram.offer`) несут название задачи;
нажатие приходит callback'ом, и мы зовём `TaskStartHandler.start_task` — ровно
как `_on_idle_answer` голосового вопроса, но с ответом в чат (возвращаемый
текст уйдёт пользователю). Клиент задачи инжектится (тесты), в проде на каждый
клик строится НОВЫЙ handler: `TaskStartHandler` фиксирует `now` в `__init__`,
а бот живёт весь процесс — кэш ставил бы устаревший `start_date` (клик в 07:46
закэшировался бы, и «утренняя зарядка», запущенная кнопкой в 08:19, получила бы
старт 07:46 — тот же класс бага, что и `task_monitor._task_handler`).

Возвращаем `(text, finish_title)` — вторую позицию `TaskOffers` использует,
чтобы прилепить к ответу кнопку «Завершить» (None — старт не состоялся,
завершать нечего).
"""

from typing import Any, Callable, Optional, Tuple

from lib.core.errors import swallowed
from lib.task_start import TaskStartHandler

# Команда, под которой старт задачи считается в статистике использования.
TASKSTART_CMD_ID = "taskstart"

PickResult = Tuple[str, Optional[str]]


def make_task_picker(handler: Optional[Any] = None,
                     record: Optional[Callable[[str], None]] = None
                     ) -> Callable[[str], PickResult]:
    """Возвращает `pick(title) -> (reply, finish_title|None)`.

    record — колбэк статистики ( matcher.record_use ): клик кнопки идёт мимо
    execute_by_id, поэтому фиксируем `taskstart` явно; None — не считаем.
    """
    def _handler() -> Any:
        """Инжект (тесты) переиспользуем; в проде — новый handler на клик."""
        return handler or TaskStartHandler()

    def pick(title: str) -> PickResult:
        try:
            result = _handler().start_task(title)
        except Exception as error:            # сбой таблицы/календаря
            swallowed("task_pick.start", error)
            return (f"Не удалось запустить «{title}» (см. лог)", None)
        if result.get("ok"):
            if record is not None:            # старт по кнопке — в статистику
                record(TASKSTART_CMD_ID)
            name = str(result.get("title") or title).strip()
            return (f"▶️ Задача «{name}» запущена", name or None)
        error = result.get("error") or f"задача «{title}» не запущена"
        return (f"❌ {error}", None)

    return pick


__all__ = ["make_task_picker", "TASKSTART_CMD_ID", "PickResult"]
