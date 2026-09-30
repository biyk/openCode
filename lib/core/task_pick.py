# TOOLTIP: Запуск задачи по нажатию кнопки Telegram (тот же путь, что ответ вслух)
"""Обработка клика кнопки «начать задачу»: старт по названию + текст в чат.

Кнопки предложения (`task_monitor` → `telegram.offer`) несут название задачи;
нажатие приходит callback'ом, и мы зовём `TaskStartHandler.start_task` — ровно
как `_on_idle_answer` голосового вопроса, но с ответом в чат (возвращаемый
текст уйдёт пользователю). Клиент задачи инжектится (тесты), в проде строится
лениво на первый клик.
"""

from typing import Any, Callable, Optional

from lib.core.errors import swallowed
from lib.task_start import TaskStartHandler


def make_task_picker(handler: Optional[Any] = None) -> Callable[[str], str]:
    """Возвращает `pick(title) -> reply`: запускает задачу, текст для чата."""
    holder: dict[str, Any] = {}

    def _handler() -> Any:
        if handler is not None:
            return handler
        if "h" not in holder:                 # лениво: без OAuth на импорте
            holder["h"] = TaskStartHandler()
        return holder["h"]

    def pick(title: str) -> str:
        try:
            result = _handler().start_task(title)
        except Exception as error:            # сбой таблицы/календаря
            swallowed("task_pick.start", error)
            return f"Не удалось запустить «{title}» (см. лог)"
        if result.get("ok"):
            name = result.get("title") or title
            return f"▶️ Задача «{name}» запущена"
        return f"❌ {result.get('error') or f'задача «{title}» не запущена'}"

    return pick


__all__ = ["make_task_picker"]
