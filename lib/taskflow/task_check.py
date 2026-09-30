# TOOLTIP: Оценка real_life_tasks: запущенные задачи (start_date ≠ 0) и переработка
"""Чистая оценка строк таблицы задач (без Google).

На вход — словари `RealLifeSheet.read_all_tasks()`, на выход — `SheetCheck`:
список запущенных (start_date ≠ 0) строк. Опрос таблицы по расписанию,
вопрос вслух и запуск задачи по ответу — в `lib/core/task_monitor.py`.

Переработка (`find_overtime`) — задача идёт дольше `task_time × множителя`
(колонка B). Проверка чистая (now_ms инжектят тесты); озвучка/
вывод/Telegram — в `lib/core/overtime.py`.

start_date пишут и JS-клиент, и голосовые команды, поэтому в колонке лежат
и числа, и текст («0», «», mс-строка) — читаем через as_int.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from lib.core.tuning import TASK_OVERTIME_MULTIPLIER
from lib.taskflow.cells import as_int
from lib.taskflow.done_calc import elapsed_minutes


@dataclass
class RunningTask:
    """Одна запущенная задача: название, uuid, старт (мс) и норма (мин)."""

    title: str
    uuid: str
    start_ms: int = 0
    task_time: int = 0


@dataclass
class SheetCheck:
    """Снимок таблицы: что сейчас запущено."""

    running: list[RunningTask] = field(default_factory=list)

    @property
    def idle(self) -> bool:
        """Ни одной запущенной задачи (start_date = 0 у всех строк)."""
        return not self.running


@dataclass
class OvertimeTask:
    """Задача в переработке: сколько идёт и какова норма (мин)."""

    title: str
    uuid: str
    elapsed: int
    plan: int


def evaluate(tasks: list[dict[str, Any]]) -> SheetCheck:
    """Строки таблицы → снимок: запущенные задачи (с стартом и нормой)."""
    running = []
    for row in tasks:
        start_ms = as_int(row.get("start_date"))
        if start_ms <= 0:
            continue
        running.append(RunningTask(
            title=str(row.get("task_title") or "").strip(),
            uuid=str(row.get("task_uuid") or "").strip(),
            start_ms=start_ms,
            task_time=as_int(row.get("task_time"))))
    return SheetCheck(running)


def find_overtime(check: SheetCheck, now_ms: int,
                  multiplier: float = TASK_OVERTIME_MULTIPLIER
                  ) -> list[OvertimeTask]:
    """Запущенные задачи, идущие дольше `task_time × множителя`.

    Норма `task_time` ≤ 0 (план не задан) — переработку не считаем: не с чем
    сравнивать. `now_ms` — текущее время в mс (epoch), инжектят тесты.
    """
    over: list[OvertimeTask] = []
    for task in check.running:
        if task.task_time <= 0 or task.start_ms <= 0:
            continue
        elapsed = elapsed_minutes(task.start_ms, now_ms)
        if elapsed > task.task_time * multiplier:
            over.append(OvertimeTask(
                title=task.title, uuid=task.uuid,
                elapsed=elapsed, plan=task.task_time))
    return over


def suggest_idle_task(tasks: list[dict[str, Any]]) -> Optional[str]:
    """Первая незапущенная задача (start_date = 0) с непустым заголовком.

    Монитор предлагает её вслух, когда ничего не запущено: «чем занимаешься?
    предлагаю задачу: …». Строки в порядке таблицы — берём самую верхнюю
    готовую. Пустая таблица / все запущены — None.
    """
    for row in tasks:
        if as_int(row.get("start_date")) > 0:
            continue
        title = str(row.get("task_title") or "").strip()
        if title:
            return title
    return None
