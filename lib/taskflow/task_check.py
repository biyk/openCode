# TOOLTIP: Оценка real_life_tasks: есть ли запущенная задача (start_date ≠ 0)
"""Чистая оценка строк таблицы задач (без Google).

На вход — словари `RealLifeSheet.read_all_tasks()`, на выход — `SheetCheck`:
список запущенных (start_date ≠ 0) строк. Опрос таблицы по расписанию,
вопрос вслух и запуск задачи по ответу — в `lib/core/task_monitor.py`.

start_date пишут и JS-клиент, и голосовые команды, поэтому в колонке лежат
и числа, и текст («0», «», mс-строка) — читаем через as_int.
"""

from dataclasses import dataclass, field
from typing import Any

from lib.taskflow.cells import as_int


@dataclass
class RunningTask:
    """Одна запущенная задача: название и uuid строки."""

    title: str
    uuid: str


@dataclass
class SheetCheck:
    """Снимок таблицы: что сейчас запущено."""

    running: list[RunningTask] = field(default_factory=list)

    @property
    def idle(self) -> bool:
        """Ни одной запущенной задачи (start_date = 0 у всех строк)."""
        return not self.running


def evaluate(tasks: list[dict[str, Any]]) -> SheetCheck:
    """Строки таблицы → снимок: запущенные задачи."""
    running = []
    for row in tasks:
        if as_int(row.get("start_date")) <= 0:
            continue
        running.append(RunningTask(
            title=str(row.get("task_title") or "").strip(),
            uuid=str(row.get("task_uuid") or "").strip()))
    return SheetCheck(running)
