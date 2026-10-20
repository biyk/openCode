# TOOLTIP: Политика перезапусков смотрителя: бэк-офф 1→2→5→15→60 с и бюджет «≤5 за 10 мин»
"""Повторные перезапуски: бэк-офф и бюджет (правила надзора за шлюзом).

Смотрителю нельзя «просто подождать cooldown»: фиксированная пауза (была 180 с)
превращается в период — шлюз перезапускался ровно каждые 180 с, и в логе
интервалы 187–202 с. Здесь пауза НАРАСТАЕТ с каждым неудачным перезапуском
(1 → 2 → 5 → 15 → 60 с, потолок) и сбрасывается, как только шлюз ожил, а
поверх неё — бюджет: не больше `budget` попыток за `window_s`. Исчерпанный
бюджет — это не «ждём ещё и пробуем дальше», а «руки прочь, зовём человека»:
цикл «умер → 35 с бут → снова умер» держит порт закрытым бо́льшую часть
времени, и долбить его бессмысленно.

Класс чистый (без потока, сети и CLI): время приходит `clock`'ом, поэтому
тесты крутят его без sleep.
"""
import time
from typing import Callable, Optional, Sequence

from lib.monitor.tuning import (MONITOR_OMNI_BACKOFF_S,
                                MONITOR_OMNI_BUDGET_RESTARTS,
                                MONITOR_OMNI_BUDGET_WINDOW_S)


class RestartPolicy:
    """Можно ли перезапускать сейчас и сколько осталось подождать."""

    def __init__(self, backoff: Sequence[float] = MONITOR_OMNI_BACKOFF_S,
                 budget: int = MONITOR_OMNI_BUDGET_RESTARTS,
                 window_s: float = MONITOR_OMNI_BUDGET_WINDOW_S,
                 clock: Callable[[], float] = time.time) -> None:
        steps = [float(s) for s in backoff] or [0.0]
        self._backoff = steps
        self._budget = max(1, int(budget))
        self._window = float(window_s)
        self._clock = clock
        self._step = 0            # сколько перезапусков подряд без успеха
        self._last: Optional[float] = None
        self._times: list = []    # моменты попыток (для бюджета окна)

    @classmethod
    def from_config(cls, config: dict) -> "RestartPolicy":
        """Политика из секции `monitor`: omni_backoff_s (список), omni_budget_*.

        Без секции (или без ключей) — дефолты из `lib/monitor/tuning.py`.
        """
        cfg = config or {}
        backoff = cfg.get("omni_backoff_s")
        return cls(
            backoff=tuple(float(x) for x in backoff) if backoff
            else MONITOR_OMNI_BACKOFF_S,
            budget=int(cfg.get("omni_budget_restarts",
                               MONITOR_OMNI_BUDGET_RESTARTS)),
            window_s=float(cfg.get("omni_budget_window_s",
                                   MONITOR_OMNI_BUDGET_WINDOW_S)))

    @property
    def budget(self) -> int:
        """Сколько перезапусков разрешено за окно (для текста доклада)."""
        return self._budget

    @property
    def window_s(self) -> float:
        """Длина окна бюджета, сек."""
        return self._window

    def _trim(self) -> None:
        now = self._clock()
        self._times = [t for t in self._times if now - t < self._window]

    def restarts(self) -> int:
        """Сколько перезапусков уже уложилось в окно бюджета."""
        self._trim()
        return len(self._times)

    def exhausted(self) -> bool:
        """Бюджет исчерпан — дальше только доклад, процесс не трогать."""
        return self.restarts() >= self._budget

    def wait_s(self) -> float:
        """Секунды ещё покрытые бэк-оффом (0 — можно перезапускать)."""
        if self._last is None:
            return 0.0
        gap = self._backoff[min(self._step - 1, len(self._backoff) - 1)]
        return max(0.0, gap - (self._clock() - self._last))

    def since_attempt(self) -> Optional[float]:
        """Сколько секунд прошло с начала последнего перезапуска (None — не было)."""
        if self._last is None:
            return None
        return self._clock() - self._last

    def on_attempt(self) -> None:
        """Заверяет попытку: она считается сразу, «удалась» станет позже."""
        now = self._clock()
        self._last = now
        self._step += 1
        self._times.append(now)
        self._trim()

    def on_healthy(self) -> None:
        """Шлюз ожил — лестница бэк-оффа обнуляется, окно бюджета остаётся."""
        self._step = 0
        self._last = None

    def step(self) -> int:
        """Текущая ступень лестницы (для тестов и журнала)."""
        return self._step


__all__ = ["RestartPolicy"]
