# lib/monitor/launch.py
"""Фабрика монитора: сбрасыватель heartbeat + (опционально) detached-дашборд.

Вызывается из main.py рядом с остальными демонами. Снимок в heartbeat пишем
всегда, когда секция `monitor` не выключена (дёшево, не мешает main); саму
страницу поднимаем/открываем только при auto_open (по умолчанию да — тогда
окошко идёт вместе с основным процессом).
"""
from typing import Any, Optional

from lib.core.errors import INFO, swallowed
from lib.monitor.heartbeat import HeartbeatWriter
from lib.monitor.registry import default_registry
from lib.monitor.tuning import MONITOR_PORT


def start_monitor(matcher: Any, output: Any,
                  registry: Optional[Any] = None) -> Optional[HeartbeatWriter]:
    """Запускает heartbeat-сброс и (по auto_open) дашборд. None — секция выкл."""
    config = {}
    if matcher is not None:
        try:
            config = matcher.get_monitor_config()
        except Exception as error:            # нет секции — живём по дефолтам
            config = swallowed("monitor.start_monitor.config", error, {}, INFO)
    if not config.get("enabled", True):
        return None
    port = int(config.get("port", MONITOR_PORT))
    writer = HeartbeatWriter(registry or default_registry())
    writer.start()
    if config.get("auto_open", True):
        try:
            from lib.monitor.dashboard import launch
            launch(port, output=output)
        except Exception as error:            # дашборд не цена основного цикла
            output.print_error(f"[Monitor] Дашборд не поднялся: {error}")
    output.print_info(
        f"[Monitor] Heartbeat пишется; дашборд: http://127.0.0.1:{port}")
    return writer


__all__ = ["start_monitor"]
