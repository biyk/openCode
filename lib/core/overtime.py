# TOOLTIP: Оповещение о переработке задачи: голос + консоль + Telegram, без ответа
"""Переработка = задача идёт дольше `task_time × множителя` (колонка B).

Встроено в фоновый цикл `task_monitor`: каждый такт (интервал = interval_min,
по умолчанию 10 мин) считает перерабатывающие задачи (`find_overtime`) и
озвучивает «всё ли в порядке», печатает в консоль/лог и дублирует в Telegram.
Ответа НЕ ждём — это не вопрос (`ask`), а сообщение (`say`): произнесли и живём
дальше.

Пока задача остаётся в переработке, оповещение ПОВТОРЯЕТСЯ на каждый такт
монитора. Раньше стояла «разовость» (одно сообщение на запущенную задачу) — из-за
чего длинная задача замолкала после первого сигнала (баг). `remind_min > 0`
задаёт минимальную паузу между повторами (0 — напоминать каждый такт).
"""

import time
from typing import Any, Callable, Optional

from lib.core.tuning import TASK_OVERTIME_MULTIPLIER, TASK_OVERTIME_TEXT
from lib.taskflow.task_check import SheetCheck, find_overtime

# Минимальная пауза между повторами оповещения по одной задаче (минуты).
# 0 — напоминать на каждый такт монитора (текущий интервал = 10 мин).
REMIND_MIN_DEFAULT = 0.0


class OvertimeNotifier:
    """Оповещение о переработке: озвучить, вывести, продублировать (без ответа).

    Повторяется, пока задача в переработке; по умолчанию — на каждый такт.
    """

    def __init__(self, say: Callable[[str], None], output: Any,
                 notify: Optional[Callable[[str], None]] = None,
                 multiplier: float = TASK_OVERTIME_MULTIPLIER,
                 remind_min: float = REMIND_MIN_DEFAULT) -> None:
        self._say = say
        self._output = output
        self._notify = notify
        self._multiplier = multiplier
        # Порог повтора в мс (0 — каждый такт).
        self._remind_ms = max(0.0, float(remind_min)) * 60_000.0
        # uuid перерабатывающей задачи -> epoch-мс последней озвучки по ней.
        self._last_ms: dict[str, int] = {}

    def check(self, sheet: SheetCheck, now_ms: Optional[int] = None) -> int:
        """Оповещает о переработках (повтор не чаще remind_min); число озвученных.

        `now_ms` инжектят тесты; по умолчанию — текущее epoch-время в мс.
        """
        moment = now_ms if now_ms is not None else int(time.time() * 1000)
        running = {task.uuid for task in sheet.running}
        # Снятые/завершённые задачи выбрасываем: при рестарте оповестим заново.
        self._last_ms = {uuid: ms for uuid, ms in self._last_ms.items()
                         if uuid in running}
        count = 0
        for over in find_overtime(sheet, moment, self._multiplier):
            last = self._last_ms.get(over.uuid)
            if last is not None and moment - last < self._remind_ms:
                continue          # ещё не пришло время повторять
            self._last_ms[over.uuid] = moment
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
