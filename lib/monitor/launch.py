# TOOLTIP: Фабрика монитора: heartbeat-сброс, смотритель OmniRouter, вкладка на доске знаний
"""Точка входа монитора сервисов из main.py.

Основной процесс делает две вещи: пишет пульс реестра в heartbeat-файл
(дёшево, не мешает main) и держит смотрителя OmniRouter (тот поднимает/
перезапускает LLM-прокси). Сама панель — вкладка «Сервисы» на сервере доски
знаний: отдельный дашборд на своём порту был бы второй сущностью с теми же
данными, поэтому при auto_open открываем доску (и поднимем её, если она
лежит — этим же `knowledge_review.launch`).
"""
from typing import Any, Optional

from lib.core.errors import INFO, swallowed
from lib.monitor.heartbeat import HeartbeatWriter
from lib.monitor.registry import ServiceRegistry, default_registry
from lib.monitor.watchdog import OmniWatchdog, build_watchdog


class Monitor:
    """То, что возвращает start_monitor: heartbeat-поток + смотрители."""

    def __init__(self, writer: HeartbeatWriter,
                 watchdog: Optional[OmniWatchdog] = None) -> None:
        self.writer = writer
        self.watchdog = watchdog

    def stop(self) -> None:
        """Останавливает всё, что подняли (main делает это при выходе)."""
        self.writer.stop()
        if self.watchdog is not None:
            self.watchdog.stop()


def open_board(output: Any, port: Optional[int] = None) -> None:
    """Поднять сервер доски (если лежит) и открыть вкладку «Сервисы»."""
    try:
        from lib.monitor.ui import TAB_ID
        from lib.voice_cmd.knowledge_review import launch as board_launch
        if board_launch(None if port is None else int(port), TAB_ID):
            output.print_error("[Monitor] Доска не поднялась — панель "
                               "недоступна (см. logs/review_server.log)")
    except Exception as error:        # панель не цена основного цикла
        output.print_error(f"[Monitor] Вкладка не открылась: {error}")


def start_monitor(matcher: Any, output: Any,
                  registry: Optional[ServiceRegistry] = None
                  ) -> Optional[Monitor]:
    """Запускает heartbeat и смотрителя. None — секция `monitor` выключена."""
    config: dict = {}
    if matcher is not None:
        try:
            config = matcher.get_monitor_config()
        except Exception as error:            # нет секции — живём по дефолтам
            config = swallowed("monitor.start_monitor.config", error, {}, INFO)
    if not config.get("enabled", True):
        return None
    reg = registry or default_registry()
    writer = HeartbeatWriter(reg)
    writer.start()
    watchdog = build_watchdog(config, reg)
    if watchdog is not None:
        watchdog.start()
    if config.get("auto_open", True):
        open_board(output, config.get("board_port"))
    output.print_info(
        "[Monitor] Heartbeat пишется; панель «Сервисы» — вкладка доски знаний")
    return Monitor(writer, watchdog)


__all__ = ["Monitor", "open_board", "start_monitor"]
