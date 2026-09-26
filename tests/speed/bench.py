"""Рекордер скоростных замеров: медиана по повторам и история метрик.

История кладётся в tests/speed/results.json — по ней сравниваем, что
дала та или иная оптимизация: record() печатает текущую медиану,
прежнее значение и дельту в процентах.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import pytest

RESULTS_FILE = Path(__file__).resolve().parent / "results.json"
MAX_HISTORY = 30


def live_only(func):
    """Тест с реальными LLM-провайдерами — только при VOICE_SPEED_LIVE=1."""
    return pytest.mark.skipif(
        os.environ.get("VOICE_SPEED_LIVE") != "1",
        reason="живой LLM: VOICE_SPEED_LIVE=1")(func)


def measure(fn, runs: int = 3) -> tuple:
    """Выполняет fn runs раз; возвращает (медиану, min, max) в секундах."""
    values = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        values.append(time.perf_counter() - t0)
    return median(values), min(values), max(values)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Recorder:
    """Меряет fn, ведёт историю метрик в results.json, печатает дельту."""

    def __init__(self, path: Path = RESULTS_FILE) -> None:
        self._path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {"metrics": {}}
        if not isinstance(data, dict) or "metrics" not in data:
            return {"metrics": {}}
        return data

    def _save(self) -> None:
        self._data["updated"] = _now()
        text = json.dumps(self._data, ensure_ascii=False, indent=2)
        self._path.write_text(text + "\n", encoding="utf-8")

    def record(self, metric: str, fn, runs: int = 3) -> float:
        """Мерит fn runs раз, дописывает медиану в историю метрики."""
        med, lo, hi = measure(fn, runs)
        entry = {"ts": _now(), "median_s": round(med, 4),
                 "min_s": round(lo, 4), "max_s": round(hi, 4), "runs": runs}
        history = self._data["metrics"].setdefault(metric, [])
        prev = history[-1]["median_s"] if history else None
        history.append(entry)
        del history[:-MAX_HISTORY]
        self._save()
        delta = ""
        if prev:
            delta = f" (prev {prev:.4f}s, {100 * (med - prev) / prev:+.1f}%)"
        print(f"[bench] {metric}: {med:.4f}s "
              f"[{lo:.4f}..{hi:.4f}] x{runs}{delta}")
        return med
