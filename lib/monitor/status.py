# lib/monitor/status.py
"""Слияние heartbeat-снимка (потоки main) и проб (внешние процессы) в один
список для GUI. Просроченный heartbeat → все сервисы main красные: дашборд
живёт отдельным процессом и честно показывает зависание основного.
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


def collect(
        heartbeat_path: Optional[str] = None,
        probe: bool = True,
        stale_s: float = MONITOR_STALE_S) -> dict:
    """Возвращает {ts, stale, age_s, services:[{id,name,state,detail}]}."""
    data = read_heartbeat(heartbeat_path or default_path())
    stale = is_stale(data, stale_s)
    services = _from_heartbeat(data, stale)
    if probe:
        services.extend(probes.external())
    ts = data.get("ts") if data else None
    return {"ts": time.time(), "stale": stale,
            "age_s": round(time.time() - float(ts), 1)
            if isinstance(ts, (int, float)) else None,
            "services": services}
