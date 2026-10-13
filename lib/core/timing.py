"""Засечки длительности: на что уходят секунды команды.

Повод: между «[Command] Распознана команда: taskdone» и первой строкой
итогова проходило ~15 c тишины. Виноваты не TTS и не Python — команду
исполняет дочерний процесс, который делает ~12 последовательных запросов к
Google API (календарь + таблица) плюс сборку клиента Calendar и печатает
что-либо только в конце.

Два уровня детальности:
  `report(label, seconds)` — грубая строка, печатается всегда: длительность
      шага целиком (исполнение команды), чтобы в консоли сразу видеть, кто
      съел время;
  `execute(request, label)` / `tick(label, seconds)` — подробная трассировка
      каждого round trip. Её включает CLI-точка входа (через `stamp_stdio`,
      §lib/core/output.py), а не голосовой цикл: в живущем процессе такие
      строки засорили бы консоль. Принудительно — `VOICE_TIMING=1`.

Строки идут в консоль (метку времени ставит TimestampedStream) и в
logs/timing.log. Запись в журнал fail-open: сбой журнала не должен валить
команду.
"""

import os
import time
from datetime import datetime
from typing import Any, Callable, Optional

from lib.core.errors import INFO, swallowed

LOG_FILE = os.path.join("logs", "timing.log")
ENV_SWITCH = "VOICE_TIMING"
_OFF = ("0", "off", "no", "false")

# Ноль отсчёта подробной трассировки этого процесса (None — выключена).
_session_t0: Optional[float] = None


def enable() -> None:
    """Начать подробную трассировку процесса; отсчёт «всего» — с этого момента."""
    global _session_t0
    if os.environ.get(ENV_SWITCH, "").strip().lower() in _OFF:
        _session_t0 = None
        return
    _session_t0 = time.perf_counter()


def disable() -> None:
    """Выключить подробную трассировку (нужно тестам и длинным демонам)."""
    global _session_t0
    _session_t0 = None


def enabled() -> bool:
    """Включена ли подробная трассировка (env VOICE_TIMING=1 включает сама)."""
    if _session_t0 is None and os.environ.get(ENV_SWITCH, "").strip() == "1":
        enable()
    return _session_t0 is not None


def _line(text: str) -> None:
    """Одна строка трассировки: консоль + logs/timing.log."""
    print(f"[Timing] {text}")
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
    except OSError as e:
        swallowed("timing.log", e, None, level=INFO)


def report(label: str, seconds: float) -> None:
    """Грубая засечка (печатается всегда): <label> за N с."""
    _line(f"{label} за {seconds:.1f} с")


def tick(label: str, seconds: float) -> None:
    """Подробная засечка: длительность шага и накопленное «всего»."""
    if not enabled():
        return
    total = time.perf_counter() - (_session_t0 or time.perf_counter())
    _line(f"{label}: {seconds:.2f} с (всего {total:.2f} с)")


def measure(label: str, fn: Callable[..., Any], *args: Any,
            **kwargs: Any) -> Any:
    """Вызывает fn(*args) с засечкой длительности (сборка клиента, TTS)."""
    t0 = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
    except Exception as e:
        tick(f"{label} — сбой {type(e).__name__}", time.perf_counter() - t0)
        raise
    tick(label, time.perf_counter() - t0)
    return result


def execute(request: Any, label: str) -> Any:
    """request.execute() с засечкой: сколько шёл этот Google round trip.

    Молчание здесь — не проглоченная ошибка: исключение летит вызывающему,
    но строка «запрос сорвался» в трассировку попадает.
    """
    return measure(label, request.execute)
