# TOOLTIP: Сборка и запуск фонового контроля задач (фабрика start_task_monitor)
"""Фабрика фонового контроля задач (секция `task_monitor` в commands.json).

Вынесено из ``task_monitor.py``, чтобы тот оставался описанием потока
``TaskMonitor``; здесь — чтение конфигурации, сборка дыр календаря
(``fun_fill``), оповещателя переработки и запуск daemon-потока. Вызывается из
``main.py`` рядом с CronScheduler.
"""

from typing import Any, Callable, Optional

from lib.core.overtime import OvertimeNotifier
from lib.core.task_monitor import TaskMonitor
from lib.core.tuning import (FUN_LOOKBACK_DAYS, FUN_MIN_GAP_MIN,
                             TASK_ANSWER_TIMEOUT_S, TASK_MONITOR_INTERVAL_S,
                             TASK_OVERTIME_MULTIPLIER)
from lib.google_calendar import GoogleCalendar
from lib.rest_check import classify_until_answer
from lib.runtime.window_title import foreground_title
from lib.taskflow.fun_fill import make_fun_fill


def start_task_monitor(worker: Any, output: Any,
                       notify: Optional[Callable[[str], None]] = None,
                       offer: Optional[Callable[[str, list], None]] = None
                       ) -> Optional[TaskMonitor]:
    """Собирает и запускает монитор по секции `task_monitor` commands.json.

    Ключи секции: enabled, interval_min, answer_timeout_s, overtime_enabled,
    overtime_multiplier; чего нет — берём из lib.core.tuning. None — секция
    выключена. Секция `fun_holes` (enabled, min_gap_min, lookback_days)
    добавляет к циклу дыры календаря; `notify` — дубль в Telegram (вопрос на
    idle и оповещение о переработке).
    """
    config = worker._matcher.get_task_monitor_config()
    if not config.get("enabled"):
        return None
    interval_s = float(config.get("interval_min",
                                  TASK_MONITOR_INTERVAL_S / 60.0)) * 60.0
    fun = None
    fun_config = worker._matcher.get_fun_holes_config()
    if fun_config.get("enabled"):
        fun = make_fun_fill(
            output,
            min_gap=float(fun_config.get("min_gap_min", FUN_MIN_GAP_MIN)),
            lookback=int(fun_config.get("lookback_days", FUN_LOOKBACK_DAYS)))
    overtime = None
    if config.get("overtime_enabled", True):
        overtime = OvertimeNotifier(
            say=worker._orchestrator.say, output=output, notify=notify,
            multiplier=float(config.get(
                'overtime_multiplier', TASK_OVERTIME_MULTIPLIER)))
    output.print_info(
        f"[TaskMonitor] Таблица задач: проверка каждые "
        f"{interval_s / 60.0:.0f} мин"
        + ("; дыры календаря → развлечения" if fun else "")
        + ("; переработка → оповещение" if overtime else ""))
    monitor = TaskMonitor(
        ask=worker._orchestrator.ask, say=worker._orchestrator.say,
        output=output, core=worker._matcher.core_phrase,
        interval_s=interval_s, fun=fun, overtime=overtime,
        title_fn=foreground_title, classify_fn=classify_until_answer,
        notify=notify, gcal=GoogleCalendar(), offer=offer,
        record=worker._matcher.record_use,
        answer_timeout_s=float(config.get("answer_timeout_s",
                                          TASK_ANSWER_TIMEOUT_S)))
    monitor.start()
    return monitor
