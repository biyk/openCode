# TOOLTIP: Оповещение о переработке задачи: голос + консоль + Telegram, без ответа
"""Переработка = задача идёт дольше `task_time × множителя` (колонка B).

Встроено в фоновый цикл `task_monitor`: каждый такт считает перерабатывающие
задачи (`find_overtime`) и на каждую ОДИН раз озвучивает «всё ли в порядке»,
печатает в консоль/лог и дублирует в Telegram. Ответа НЕ ждём — это не вопрос
(`ask`), а сообщение (`say`): произнесли и живём дальше.

Повтор на ту же запущенную задачу не накладываем, пока она не остановится
(uuid пропадёт из `running` — запись сброшена и переработка заведётся заново).
"""

import time
from typing import Any, Callable, Optional

from lib.core.tuning import TASK_OVERTIME_MULTIPLIER, TASK_OVERTIME_TEXT
from lib.taskflow.task_check import SheetCheck, find_overtime


class OvertimeNotifier:
    """Разовое оповещение о переработке: озвучить, вывести, продублировать."""

    def __init__(self, say: Callable[[str], None], output: Any,
                 notify: Optional[Callable[[str], None]] = None,
                 multiplier: float = TASK_OVERTIME_MULTIPLIER) -> None:
        self._say = say
        self._output = output
        self._notify = notify
        self._multiplier = multiplier
        # uuid задач, о переработке которых уже предупредили в этом запуске.
        self._notified: set[str] = set()

    def check(self, sheet: SheetCheck, now_ms: Optional[int] = None) -> int:
        """Оповещает о новых переработках; возвращает число озвученных.

        `now_ms` инжектят тесты; по умолчанию — текущее epoch-время в мс.
        """
        moment = now_ms if now_ms is not None else int(time.time() * 1000)
        running = {task.uuid for task in sheet.running}
        # Снятые/завершённые задачи больше не держим: их переработка
        # заведётся заново, если задача стартует повторно.
        self._notified &= running
        count = 0
        for over in find_overtime(sheet, moment, self._multiplier):
            if over.uuid in self._notified:
                continue
            self._notified.add(over.uuid)
            count += 1
            self._announce(over)
        return count

    def _announce(self, over: Any) -> None:
        """Одно оповещение: консоль/лог + голос + Telegram (без ответа)."""
        message = TASK_OVERTIME_TEXT.format(
            title=over.title, elapsed=over.elapsed, plan=over.plan)
        self._output.print_info(f"[Overtime] {message}")
        self._say(message)
        if self._notify is not None:
            self._notify(message)


__all__ = ["OvertimeNotifier"]
