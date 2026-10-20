# TOOLTIP: Смотритель OmniRouter: поднимает умерший, не трогает занятой и зависший вслепую
"""Смотритель за внешним процессом OmniRouter (daemon-поток, как task_monitor).

OmniRouter держит на себе LLM-ответы (фолбэк Лайи, rest-классификация, оживление), а
сам — чужой процесс. Правило: убивать живое дороже, чем кажется.
Вердикты (подробно — AGENTS.md §4.13): health 200 → зелёный; порт закрыт →
поднять (жив pid — сначала `stop` и дренаж); порт открыт и молчит → не
трогать до `hang_after_s` И нуля соединений: штатный long-запрос глушит
/healthz на минуты, а рестарт режет стрим (499); соединения
не посчитать → тоже не трогать; бэк-офф/бюджет исчерпан → красный ряд
и доклад человеку, руки прочь. Прогрев снимает ПЕРВЫЙ 200, а не часы;
сбой проверки — fail-safe: не валит смотрителя, запрет разрушительному.
"""
import threading
import time
from typing import Any, Callable, Optional

from lib.core.errors import swallowed
from lib.monitor import omni, omni_proc
from lib.monitor.policy import RestartPolicy
from lib.monitor.registry import ERROR, IDLE, WORKING, ServiceRegistry
from lib.monitor.tuning import (MONITOR_OMNI_HANG_AFTER_S,
                                MONITOR_OMNI_HANG_FAILS, MONITOR_OMNI_URL,
                                MONITOR_OMNI_WARMUP_S, MONITOR_WATCHDOG_S)

SERVICE_ID = "omniroute"
SERVICE_NAME = "OmniRouter (LLM)"


class OmniWatchdog(threading.Thread):
    """Цикл «проверка → подъём/перезапуск по правилам» с докладом в реестр."""

    def __init__(self, registry: ServiceRegistry,
                 base_url: str = MONITOR_OMNI_URL,
                 interval_s: float = MONITOR_WATCHDOG_S,
                 hang_fails: int = MONITOR_OMNI_HANG_FAILS,
                 hang_after_s: float = MONITOR_OMNI_HANG_AFTER_S,
                 warmup_s: float = MONITOR_OMNI_WARMUP_S,
                 policy: Optional[RestartPolicy] = None,
                 health: Optional[Callable[[str], bool]] = None,
                 listening: Optional[Callable[[str], bool]] = None,
                 connections: Optional[Callable[[int], Optional[int]]] = None,
                 running: Optional[Callable[[], Optional[bool]]] = None,
                 restarter: Optional[Callable[[int, bool], tuple]] = None,
                 notifier: Optional[Callable[[str], None]] = None) -> None:
        super().__init__(daemon=True, name="monitor-omni")
        self._registry = registry
        self._base = base_url
        self._interval = float(interval_s)
        self._hang_fails = max(1, int(hang_fails))
        self._hang_after = float(hang_after_s)
        self._warmup = float(warmup_s)
        self._policy = policy or RestartPolicy()
        self._health = health or omni.is_healthy
        self._listening = listening or omni.is_listening
        self._connections = connections or omni_proc.active_connections
        self._running = running or omni_proc.server_running
        self._restarter = restarter or omni.restart
        self._notifier = notifier
        # Не `_stop`: у threading.Thread есть свой метод `_stop`, и
        # одноимённый атрибут ломает join() (`'Event' object is not callable`).
        self._stop_event = threading.Event()
        self._fails = 0
        self._since: Optional[float] = None   # с какого момента молчим
        self._warned = False

    def run(self) -> None:
        while not self._stop_event.is_set():
            self.tick()
            self._stop_event.wait(self._interval)

    def stop(self) -> None:
        self._stop_event.set()

    def _report(self, state: str, detail: str = "") -> None:
        self._registry.report(SERVICE_ID, SERVICE_NAME, state, detail)

    def _notify(self, text: str) -> None:
        """Оповещение человека в консоль/лог (ряд в панели — сам `_report`)."""
        if self._notifier is None:
            return
        try:
            self._notifier(text)
        except Exception as error:        # оповещение не цена такта
            swallowed("monitor.watchdog.notify", error)

    def tick(self) -> str:
        """Один проход проверки; возвращает вердикт (для тестов и журнала)."""
        try:
            if self._health(self._base):
                self._on_up()
                return "up"
            if not self._listening(self._base):
                return self._restart("не запущен", drain=bool(self._running()))
            left = self._warmup_left()
            if left > 0:
                self._report(IDLE, f"греется после перезапуска ({left:.0f} с)")
                return "warmup"
            self._count_fail()
            if not self._hang_expired():
                self._report(IDLE, self._silent_text())
                return "degraded"
            busy = self._connections(omni.port_from_url(self._base))
            if busy is None:
                self._report(ERROR, "ответа нет, соединений не посчитать")
                return "unknown"
            if busy:
                self._report(ERROR, f"ответа нет {self._silent_for():.0f} с, "
                                    f"но идут запросы ({busy}) — не трогаю")
                return "busy"
            return self._restart("завис", drain=True)
        except Exception as error:            # смотритель не роняет поток
            swallowed("monitor.watchdog.tick", error)
            return "error"

    def _on_up(self) -> None:
        """Ожил: молчание, счётчики и лестница бэк-оффа сброшены, прогрев снят."""
        since = self._policy.since_attempt()   # ДО сброса: после него не узнать
        self._fails = 0
        self._since = None
        self._warned = False
        self._policy.on_healthy()
        ours = since is not None and since <= 60
        self._report(WORKING, "поднят смотрителем" if ours else self._base)

    def _count_fail(self) -> None:
        """Одна неудачная проба на открытом порту (молчание копится с начала)."""
        if self._since is None:
            self._since = time.time()
        self._fails += 1

    def _silent_for(self) -> float:
        """Сколько секунд подряд ни одной успешной пробы."""
        return 0.0 if self._since is None else time.time() - self._since

    def _silent_text(self) -> str:
        return (f"порт открыт, ответа нет ({self._fails}/{self._hang_fails}, "
                f"{self._silent_for():.0f} с из {self._hang_after:.0f})")

    def _hang_expired(self) -> bool:
        """И число проб, и время молчания на исходе — только тогда это зависание."""
        return (self._fails >= self._hang_fails
                and self._silent_for() >= self._hang_after)

    def _warmup_left(self) -> float:
        """Секунды, ещё покрытые паузой на подъём сервера (0 — кончилась)."""
        since = self._policy.since_attempt()
        return 0.0 if since is None else max(0.0, self._warmup - since)

    def _restart(self, reason: str, drain: bool) -> str:
        """Подъём/перезапуск собственным CLI OmniRouter, если это разрешено."""
        wait = self._policy.wait_s()
        if wait > 0:
            self._report(IDLE, f"{reason}: бэк-офф ({wait:.0f} с)")
            return "backoff"
        if self._policy.exhausted():
            return self._give_up(reason)
        if drain and self._health(self._base):
            self._on_up()                     # оглядка перед остановкой
            return "up"
        port = omni.port_from_url(self._base)
        self._policy.on_attempt()
        self._fails = 0
        self._since = None
        self._report(IDLE, f"{reason}: перезапускаю")
        self._notify(f"[Monitor] OmniRouter: {reason} — перезапускаю :{port}")
        ok, detail = self._restarter(port, drain)
        if ok:
            self._report(WORKING, f"{reason}: подняли заново · {detail}")
            return "restarted"
        self._report(ERROR, f"{reason}: {detail}")
        return "failed"

    def _give_up(self, reason: str) -> str:
        """Бюджет исчерпан: процесс не трогаем, зовём человека (правило 5)."""
        detail = (f"{reason}: {self._policy.restarts()} перезапусков за "
                  f"{self._policy.window_s / 60:.0f} мин — не трогаю, нужен человек")
        self._report(ERROR, detail)
        if not self._warned:
            self._warned = True
            self._notify(f"[Monitor] OmniRouter: {detail}")
        return "budget"


def build_watchdog(config: dict, registry: ServiceRegistry,
                   output: Any = None) -> Optional[OmniWatchdog]:
    """Смотритель по секции `monitor`; пустая секция = по умолчанию включён."""
    cfg = config or {}
    if not cfg.get("omni_enabled", True):
        return None
    return OmniWatchdog(registry,
                        base_url=str(cfg.get("omni_url") or MONITOR_OMNI_URL),
                        interval_s=float(cfg.get("omni_interval_s", MONITOR_WATCHDOG_S)),
                        hang_fails=int(cfg.get("omni_hang_fails", MONITOR_OMNI_HANG_FAILS)),
                        hang_after_s=float(cfg.get("omni_hang_after_s", MONITOR_OMNI_HANG_AFTER_S)),
                        warmup_s=float(cfg.get("omni_warmup_s", MONITOR_OMNI_WARMUP_S)),
                        policy=RestartPolicy.from_config(cfg),
                        notifier=output.print_error if output is not None else None)
