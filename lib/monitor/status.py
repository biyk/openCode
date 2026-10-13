# lib/monitor/status.py
"""Слияние heartbeat-снимка (потоки main) и проб (внешние процессы) в один
список для вкладки «Сервисы». Просроченный heartbeat → все сервисы main
красные: вкладку отдаёт процесс доски знаний, отдельно от основного, и потому
честно показывает его зависание.
"""
import time
from typing import Optional

from lib.monitor import probes
from lib.monitor.heartbeat import default_path, is_stale, read_heartbeat
from lib.monitor.registry import ERROR, NEVER
from lib.monitor.tuning import MONITOR_STALE_S


def _from_heartbeat(data: Optional[dict], stale: bool) -> list:
    services = (data or {}).get("services", {}) or {}
    if not services:
        return [{"id": "main", "name": "Основной процесс",
                 "state": NEVER if data is None else ERROR,
                 "detail": "нет heartbeat-файла" if data is None
                 else "пустой снимок"}]
    out = []
    for sid, rec in services.items():
        out.append({
            "id": sid,
            "name": rec.get("name", sid),
            "state": ERROR if stale else rec.get("state", NEVER),
            "detail": ("основной процесс не отвечает" if stale
                       else rec.get("detail", "")),
        })
    return out


def _merge(rows: list, probed: list, stale: bool) -> list:
    """Пробы дополняют снимок; зависший main не вправе врать за чужой порт.

    Пока heartbeat свежий, строка сервиса остаётся как её доложил сам процесс
    (смотритель знает, что он чинил); при просрочке берём факт с порта.
    """
    index = {r["id"]: i for i, r in enumerate(rows)}
    for p in probed:
        i = index.get(p["id"])
        if i is None:
            rows.append(p)
        elif stale:
            rows[i] = p
    return rows


def collect(
        heartbeat_path: Optional[str] = None,
        probe: bool = True,
        stale_s: float = MONITOR_STALE_S) -> dict:
    """Возвращает {ts, stale, age_s, services:[{id,name,state,detail}]}.

    services строится из снимка heartbeat и (опционально) проб портов."""
    data = read_heartbeat(heartbeat_path or default_path())
    stale = is_stale(data, stale_s)
    services = _from_heartbeat(data, stale)
    if probe:
        services = _merge(services, probes.external(), stale)
    ts = data.get("ts") if data else None
    return {"ts": time.time(), "stale": stale,
            "age_s": round(time.time() - float(ts), 1)
            if isinstance(ts, (int, float)) else None,
            "services": services}
