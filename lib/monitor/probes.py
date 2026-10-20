# lib/monitor/probes.py
"""Пробы внешних процессов (живут НЕ в основном процессе, по факту порта).

Laya (:8080 /health), браузер CDP (:9222 /json/version), доска знаний
(:8765 /api/ping), OmniRouter (:20128 /healthz) — отдельные процессы. Их
«живость» определяет вкладка монитора на сервере доски: читает heartbeat и
сам пробабит порты, ровно как `is_up()` в knowledge_review и `_health()` в
laya_decision. Не отвечает = не запущен (по требованию поднимается) —
показываем как idle.

Для шлюза проба берётся с таймаутом смотрителя (`MONITOR_OMNI_HEALTH_TIMEOUT_S`),
а не общим (1 с): под нагрузкой он отвечает и за 7 с, и за 10 с, и в панели это
не «не запущен», а «занят».
"""
import urllib.request

from lib.monitor.registry import IDLE, WORKING
from lib.monitor.tuning import (MONITOR_BOARD_PORT,
                                MONITOR_OMNI_HEALTH_PATH,
                                MONITOR_OMNI_HEALTH_TIMEOUT_S,
                                MONITOR_OMNI_URL,
                                MONITOR_PROBE_CDP_PORT,
                                MONITOR_PROBE_LAYA_URL,
                                MONITOR_PROBE_TIMEOUT_S)


def http_ok(url: str, timeout: float = MONITOR_PROBE_TIMEOUT_S) -> bool:
    """Отвечает ли URL кодом 2xx; любой сбой (порт закрыт/таймаут) — False."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= getattr(r, "status", 200) < 300
    except (OSError, ValueError):
        return False  # лежит/не поднялся — штатный ответ пробы, не ошибка


def probe_laya(url: str = MONITOR_PROBE_LAYA_URL) -> dict:
    ok = http_ok(url.rstrip("/") + "/health")
    return {"state": WORKING if ok else IDLE,
            "detail": url if ok else "не отвечает (поднимется по команде)"}


def probe_cdp(port: int = MONITOR_PROBE_CDP_PORT) -> dict:
    ok = http_ok(f"http://127.0.0.1:{port}/json/version")
    return {"state": WORKING if ok else IDLE,
            "detail": f":{port}" if ok else f"порт :{port} не отвечает"}


def probe_board(port: int = MONITOR_BOARD_PORT) -> dict:
    ok = http_ok(f"http://127.0.0.1:{port}/api/ping")
    return {"state": WORKING if ok else IDLE,
            "detail": f":{port}" if ok else f"порт :{port} не отвечает"}


def probe_omni(url: str = MONITOR_OMNI_URL) -> dict:
    ok = http_ok(url.rstrip("/") + MONITOR_OMNI_HEALTH_PATH,
                 MONITOR_OMNI_HEALTH_TIMEOUT_S)
    return {"state": WORKING if ok else IDLE,
            "detail": url if ok else "не отвечает (поднимет смотритель)"}


def external() -> list:
    """Список внешних сервисов с текущим состоянием (для слияния в GUI)."""
    return [
        {"id": "laya", "name": "Laya (решатель)", **probe_laya()},
        {"id": "browser", "name": "Браузер (CDP)", **probe_cdp()},
        {"id": "board", "name": "Доска знаний", **probe_board()},
        {"id": "omniroute", "name": "OmniRouter (LLM)", **probe_omni()},
    ]
