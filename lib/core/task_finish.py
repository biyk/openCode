# TOOLTIP: Завершение задачи по кнопке Telegram (тот же путь, что «завершил задачу»)
"""Обработка клика кнопки «Завершить»: стоп/-done по названию + текст в чат.

Кнопка лепится к ответу старта (см. `TaskOffers.handle_callback`): нажатие
приносит заголовок, и мы зовём `TaskCompleteHandler.complete_task` — тот же
путь, что голосовая команда `taskdone` (`lib/task_complete.py`), с выбором
ветви ⏹/✅ по состоянию строки. Клиент инжектится (тесты); в проде на
каждый клик строится НОВЫЙ handler — `TaskCompleteHandler` фиксирует `now`
в `__init__`, и кэш ставил бы устаревшую длительность отрезка (та же
причина, что у `task_pick._handler`).

Возвращаем только текст — кнопка «снова начать» не нужна: следующий старт
пользователь делает через новый вопрос монитора.
"""

from typing import Any, Callable, Optional

from lib.core.errors import swallowed
from lib.task_complete import TaskCompleteHandler

# Команда, под которой завершение считается в статистике использования.
TASKDONE_CMD_ID = "taskdone"


def _format(result: dict, fallback_title: str) -> str:
    """Человеческий ответ: ⏹/✅ + длительность и награда; ошибка — ❌."""
    if result.get("skipped"):
        name = str(result.get("title") or fallback_title).strip()
        return f"✅ «{name}» уже засчитана сегодня"
    if not result.get("ok"):
        error = result.get("error") or (
            f"задача «{fallback_title}» не завершена")
        return f"❌ {error}"
    name = str(result.get("title") or fallback_title).strip()
    money = float(result.get("money") or 0.0)
    if result.get("branch") == "⏹":
        minutes = result.get("elapsed_minutes")
        return (f"⏹ Задача «{name}» завершена: "
                f"{minutes} мин, награда {money:.2f}")
    minutes = result.get("time_spent")
    return (f"✅ Задача «{name}» засчитана: "
            f"{minutes} мин, награда {money:.2f}")


def make_task_finisher(
    handler: Optional[Any] = None,
    record: Optional[Callable[[str], None]] = None
) -> Callable[[str], str]:
    """Возвращает `finish(title) -> reply`: завершает задачу, текст для чата.

    record — колбэк статистики (`matcher.record_use`): клик кнопки идёт мимо
    `execute_by_id`, поэтому фиксируем `taskdone` явно; None — не считаем.
    """
    def _handler() -> Any:
        """Инжект (тесты) переиспользуем; в проде — новый handler на клик."""
        return handler or TaskCompleteHandler()

    def finish(title: str) -> str:
        try:
            result = _handler().complete_task(title)
        except Exception as error:            # сбой таблицы/календаря
            swallowed("task_finish.complete", error)
            return f"Не удалось завершить «{title}» (см. лог)"
        if result.get("ok") and record is not None:
            record(TASKDONE_CMD_ID)           # завершение по кнопке — в статистику
        return _format(result, title)

    return finish


__all__ = ["make_task_finisher", "TASKDONE_CMD_ID"]
