# TOOLTIP: Смотритель OmniRouter: поднимает мёртвый прокси и перезапускает зависший
"""Смотритель за внешним процессом OmniRouter (daemon-поток, как task_monitor).

OmniRouter держит на себе ответы LLM (фолбэк Лайи, rest-классификация,
оживление ответа), а сам — чужой процесс: упал и молчит, ассистент просто
начинает «тупить». Поэтому не только показываем его в GUI, но и чиним:

  порт закрыт            → процесс мёртв → `restart` сразу;
  порт открыт, health нет → считаем зависшим после `hang_fails` подряд → restart;
  health отвечает        → зелёный, счётчик неудач обнуляется.

Перезапуск не чаще `cooldown_s` — старт OmniRouter медленный, иначе крутили
бы рестарт на каждом такте, пока сервер греется. Тот же подъём учитывает и
`warmup_s`: после нашего рестарта порт открыт с первой секунды, а
`/api/health` отвечает только через ~45 с, и эти такты — «греется», а не
«завис». Любой сбой проверки — fail-open: смотритель не должен ронять ни
себя, ни основной процесс.
"""
import threading
import time
from typing import Callable, Optional

from lib.core.errors import swallowed
from lib.monitor import omni
from lib.monitor.registry import ERROR, IDLE, WORKING, ServiceRegistry
from lib.monitor.tuning import (MONITOR_OMNI_COOLDOWN_S, MONITOR_OMNI_HANG_FAILS,
                                MONITOR_OMNI_URL, MONITOR_OMNI_WARMUP_S,
                                MONITOR_WATCHDOG_S)

SERVICE_ID = "omniroute"
SERVICE_NAME = "OmniRouter (LLM)"


class OmniWatchdog(threading.Thread):
    """Цикл «проверка → подъём/перезапуск» с докладом в реестр состояний."""

    def __init__(self, registry: ServiceRegistry,
                 base_url: str = MONITOR_OMNI_URL,
                 interval_s: float = MONITOR_WATCHDOG_S,
                 hang_fails: int = MONITOR_OMNI_HANG_FAILS,
                 cooldown_s: float = MONITOR_OMNI_COOLDOWN_S,
                 warmup_s: float = MONITOR_OMNI_WARMUP_S,
                 health: Optional[Callable[[str], bool]] = None,
                 listening: Optional[Callable[[str], bool]] = None,
                 restarter: Optional[Callable[[int], tuple]] = None) -> None:
        super().__init__(daemon=True, name="monitor-omni")
        self._registry = registry
        self._base = base_url
        self._interval = float(interval_s)
        self._hang_fails = max(1, int(hang_fails))
        self._cooldown = float(cooldown_s)
        self._warmup = float(warmup_s)
        self._health = health or omni.is_healthy
        self._listening = listening or omni.is_listening
        self._restarter = restarter or omni.restart
        # Не `_stop`: у threading.Thread есть свой метод `_stop`, и
        # одноимённый атрибут ломает join() (`'Event' object is not callable`).
        self._stop_event = threading.Event()
        self._fails = 0
        self._last_restart = 0.0

    def run(self) -> None:
        while not self._stop_event.is_set():
            self.tick()
            self._stop_event.wait(self._interval)

    def stop(self) -> None:
        self._stop_event.set()

    def _report(self, state: str, detail: str = "") -> None:
        self._registry.report(SERVICE_ID, SERVICE_NAME, state, detail)

    def tick(self) -> str:
        """Один проход проверки; возвращает вердикт (для тестов и журнала)."""
        try:
            if self._health(self._base):
                self._fails = 0
                fresh = time.time() - self._last_restart > 60
                self._report(WORKING,
                             self._base if fresh else "поднят смотрителем")
                return "up"
            if not self._listening(self._base):
                return self._restart("не запущен")
            left = self._warmup_left()
            if left > 0:
                self._fails = 0
                self._report(IDLE, f"греется после перезапуска ({left:.0f} с)")
                return "warmup"
            self._fails += 1
            if self._fails < self._hang_fails:
                self._report(
                    IDLE, f"порт открыт, /api/health молчит "
                          f"({self._fails}/{self._hang_fails})")
                return "degraded"
            return self._restart("завис")
        except Exception as error:            # смотритель не роняет поток
            swallowed("monitor.watchdog.tick", error)
            return "error"

    def _warmup_left(self) -> float:
        """Секунды, ещё покрытые паузой на подъём сервера (0 — пауза кончилась)."""
        if not self._last_restart:
            return 0.0
        return max(0.0, self._warmup - (time.time() - self._last_restart))

    def _restart(self, reason: str) -> str:
        """Подъём/перезапуск собственным CLI OmniRouter."""
        if time.time() - self._last_restart < self._cooldown:
            self._report(ERROR, f"{reason}: перезапуск уже был, ждём")
            return "cooldown"
        self._last_restart = time.time()
        self._fails = 0
        self._report(IDLE, f"{reason}: перезапускаю")
        ok, detail = self._restarter(omni.port_from_url(self._base))
        if ok:
            self._report(WORKING, f"{reason}: подняли заново · {detail}")
            return "restarted"
        self._report(ERROR, f"{reason}: {detail}")
        return "failed"


def build_watchdog(config: dict,
                   registry: ServiceRegistry) -> Optional[OmniWatchdog]:
    """Смотритель по секции `monitor`; пустая секция = по умолчанию включён."""
    if not (config or {}).get("omni_enabled", True):
        return None
    return OmniWatchdog(
        registry,
        base_url=str(config.get("omni_url") or MONITOR_OMNI_URL),
        interval_s=float(config.get("omni_interval_s", MONITOR_WATCHDOG_S)),
        hang_fails=int(config.get("omni_hang_fails", MONITOR_OMNI_HANG_FAILS)),
        cooldown_s=float(config.get("omni_cooldown_s", MONITOR_OMNI_COOLDOWN_S)),
        warmup_s=float(config.get("omni_warmup_s", MONITOR_OMNI_WARMUP_S)))
