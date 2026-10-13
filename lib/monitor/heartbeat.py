# lib/monitor/heartbeat.py
"""Сброс снимка реестра в heartbeat-файл (атомарно) и чтение дашбордом.

Транспорт между двумя процессами — самый простой, что работает: маленький
JSON пишется атомарно (os.replace) раз в MONITOR_HEARTBEAT_S; дашборд читает
его и смотрит на штамп времени. Просрочка (MONITOR_STALE_S) = основной
процесс завис/умер — его сервисы в GUI становятся красными.

Файл — runtime-данные (как command_stats.json): temp/services_heartbeat.json,
в .gitignore. Путь можно передать (тесты пишут во временный каталог).
"""
import json
import os
import threading
import time
from typing import Optional

from lib.core.errors import swallowed
from lib.monitor.registry import ServiceRegistry
from lib.monitor.tuning import MONITOR_HEARTBEAT_S, MONITOR_STALE_S

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_PATH = os.path.join(
    REPO_ROOT, "temp", "services_heartbeat.json")


def default_path() -> str:
    """Абсолютный путь heartbeat-файла (не зависит от cwd)."""
    return DEFAULT_PATH


def write_heartbeat(registry: ServiceRegistry, path: str) -> None:
    """Атомарно пишет снимок со штампом времени; сбой — логируем (fail-open)."""
    data = {"ts": time.time(), "services": registry.snapshot()}
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as error:
        swallowed("monitor.heartbeat.write", error)


def read_heartbeat(path: str) -> Optional[dict]:
    """Читает снимок; None — файла нет/битый (дашборд покажет «не отвечает»)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as error:
        return swallowed("monitor.heartbeat.read", error, None)


def heartbeat_age(data: Optional[dict]) -> Optional[float]:
    """Сколько секунд назад был сброс; None — штамп недоступен."""
    if not data or not isinstance(data.get("ts"), (int, float)):
        return None
    return time.time() - float(data["ts"])


def is_stale(data: Optional[dict],
             stale_s: float = MONITOR_STALE_S) -> bool:
    """True, если heartbeat просрочен (нет файла/штампа или старый)."""
    age = heartbeat_age(data)
    return age is None or age > stale_s


class HeartbeatWriter(threading.Thread):
    """Daemon-поток: раз в interval сбрасывает снимок реестра в файл."""

    def __init__(self, registry: ServiceRegistry, path: Optional[str] = None,
                 interval: float = MONITOR_HEARTBEAT_S) -> None:
        super().__init__(daemon=True, name="monitor-heartbeat")
        self._registry = registry
        self._path = path or default_path()
        self._interval = interval
        # Не `_stop`: у threading.Thread есть собственный метод `_stop()`,
        # и атрибут-Event перекрывает его — join() падает на
        # `TypeError: 'Event' object is not callable`.
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            write_heartbeat(self._registry, self._path)
            self._stop_event.wait(self._interval)

    def stop(self) -> None:
        self._stop_event.set()
