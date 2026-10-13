# lib/monitor/registry.py
"""Реестр живности сервисов основного процесса (для GUI-монитора).

Каждый фоновый поток отмечает своё состояние; сбрасыватель heartbeat пишет
снимок на диск, дашборд читает. Реестр — потокобезопасный словарь с замком
(как StatusStore), без внешних зависимостей.

Состояния и цвет в GUI:
  working  🟢 поток жив и прямо сейчас делает работу;
  idle     🟡 поток жив, но между циклами / пустая очередь («спит, ждёт»);
  disabled 🔴 секция commands.json выключена — намеренно не работает;
  error    🔴 упал/не поднялся/просрочил heartbeat;
  never    🔴 ещё ни разу не запускался в этой сессии.
"""
import threading
from typing import Optional

from lib.core.errors import swallowed

WORKING = "working"
IDLE = "idle"
DISABLED = "disabled"
ERROR = "error"
NEVER = "never"

# Состояния, при которых сервис считается «не живым» (красный в GUI).
RED_STATES = frozenset((DISABLED, ERROR, NEVER))


class ServiceRegistry:
    """Идемпотентная таблица `service_id -> {name, state, detail}`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._services: dict[str, dict] = {}

    def report(self, service_id: str, name: str, state: str,
               detail: str = "") -> None:
        """Отмечает состояние сервиса; сбой записи не роняет вызвавший поток."""
        try:
            with self._lock:
                self._services[service_id] = {
                    "name": name, "state": state, "detail": detail}
        except Exception as error:        # реестр не цена сервиса
            swallowed("monitor.registry.report", error)

    def snapshot(self) -> dict:
        """Копия всех состояний (для сброса в heartbeat-файл)."""
        with self._lock:
            return {sid: dict(rec)
                    for sid, rec in self._services.items()}


_default: Optional[ServiceRegistry] = None
_default_lock = threading.Lock()


def default_registry() -> ServiceRegistry:
    """Общий реестр процесса (его использует heartbeat-сбрасыватель)."""
    global _default
    with _default_lock:
        if _default is None:
            _default = ServiceRegistry()
        return _default


def report(service_id: str, name: str, state: str, detail: str = "") -> None:
    """Быстрый вызов в общий реестр: одна строка в цикле потока."""
    default_registry().report(service_id, name, state, detail)
