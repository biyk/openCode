"""Тесты смотрителя OmniRouter (`lib/monitor/watchdog.py`).

Проверяется таблица решений — «мёртв → поднять», «порт открыт, health молчит →
перезапустить после N неудач», «cooldown не даёт крутить рестарт подряд» — на
инжектированных колбэках: живого процесса и CLI здесь не нужно. Ветка прогрева
после рестарта — в test_watchdog_warmup.py (лимит 200 строк, §9).
"""
import inspect
import time

from lib.monitor import watchdog as wd
from lib.monitor.registry import ERROR, IDLE, WORKING, ServiceRegistry
from lib.monitor.tuning import (MONITOR_OMNI_COOLDOWN_S,
                                MONITOR_OMNI_HANG_FAILS, MONITOR_OMNI_URL,
                                MONITOR_OMNI_WARMUP_S, MONITOR_WATCHDOG_S)


class _Wd(wd.OmniWatchdog):
    """Смотритель с заранее известными ответами проб и рестартера."""

    def __init__(self, health=None, listening=None, restarter=None, **kw):
        self.events = []
        super().__init__(ServiceRegistry(),
                         health=health or (lambda base: True),
                         listening=listening or (lambda base: True),
                         restarter=restarter or self._ok, **kw)

    def _ok(self, port):
        return True, f"ok:{port}"

    def _report(self, state, detail=""):
        self.events.append((state, detail))
        super()._report(state, detail)

    def row(self):
        return self._registry.snapshot().get(wd.SERVICE_ID, {})


def test_healthy_is_green_and_resets_fails():
    w = _Wd(health=lambda base: True)
    w._fails = 2
    assert w.tick() == "up"
    assert w._fails == 0
    assert w.row()["state"] == WORKING


def test_dead_port_is_raised_at_once():
    calls = []

    def _restart(port):
        calls.append(port)
        return True, "поднят"

    w = _Wd(health=lambda base: False, listening=lambda base: False,
            restarter=_restart)
    assert w.tick() == "restarted"
    assert calls == [20128]
    assert w.row()["state"] == WORKING
    assert "не запущен" in w.row()["detail"]


def test_open_port_without_health_needs_several_fails():
    w = _Wd(health=lambda base: False, listening=lambda base: True,
            restarter=lambda port: (True, "ok"), hang_fails=3)
    assert w.tick() == "degraded"
    assert w.tick() == "degraded"
    assert w.row()["state"] == IDLE
    assert "2/3" in w.events[1][1]
    assert w.tick() == "restarted"


def test_restart_failure_is_red_not_exception():
    w = _Wd(health=lambda base: False, listening=lambda base: False,
            restarter=lambda port: (False, "CLI omniroute не найден"))
    assert w.tick() == "failed"
    assert w.row()["state"] == ERROR
    assert "не найден" in w.row()["detail"]


def test_cooldown_blocks_second_restart():
    w = _Wd(health=lambda base: False, listening=lambda base: False,
            restarter=lambda port: (True, "ok"), cooldown_s=180)
    assert w.tick() == "restarted"
    assert w.tick() == "cooldown"
    assert w.row()["state"] == ERROR
    assert "перезапуск уже был" in w.row()["detail"]


def test_cooldown_expiry_allows_restart_again():
    w = _Wd(health=lambda base: False, listening=lambda base: False,
            restarter=lambda port: (True, "ok"), cooldown_s=1)
    w.tick()
    w._last_restart = time.time() - 2
    assert w.tick() == "restarted"


def test_probe_crash_does_not_raise_out_of_tick():
    def _boom(base):
        raise RuntimeError("метр не ответил")

    w = _Wd(health=_boom)
    assert w.tick() == "error"          # вердикт вместо исключения


def test_restart_detail_recognized_after_fresh_up():
    w = _Wd(health=lambda base: True)
    w._last_restart = time.time()       # перезапускали только что
    assert w.tick() == "up"
    assert "поднят смотрителем" in w.row()["detail"]
    w._last_restart = time.time() - 120
    assert w.tick() == "up"
    assert w.row()["detail"] == MONITOR_OMNI_URL


def test_run_loop_ticks_until_stopped():
    """Поток-смотритель циклится и корректно останавливается."""
    w = _Wd(health=lambda base: True, interval_s=0.01)
    w.start()
    deadline = time.time() + 2
    while time.time() < deadline and not w.events:
        time.sleep(0.01)
    w.stop()
    w.join(1)
    assert w.events and not w.is_alive()


def test_defaults_come_from_tuning():
    p = inspect.signature(wd.OmniWatchdog.__init__).parameters
    assert p["base_url"].default == MONITOR_OMNI_URL
    assert p["interval_s"].default == MONITOR_WATCHDOG_S
    assert p["hang_fails"].default == MONITOR_OMNI_HANG_FAILS
    assert p["cooldown_s"].default == MONITOR_OMNI_COOLDOWN_S
    assert p["warmup_s"].default == MONITOR_OMNI_WARMUP_S
    assert wd.SERVICE_ID == "omniroute"


def test_build_watchdog_reads_config():
    w = wd.build_watchdog({"omni_enabled": True, "omni_url": "http://h:1",
                           "omni_interval_s": 7, "omni_hang_fails": 5,
                           "omni_cooldown_s": 9, "omni_warmup_s": 42},
                          ServiceRegistry())
    assert w is not None
    assert w._base == "http://h:1"
    assert w._interval == 7.0
    assert w._hang_fails == 5
    assert w._cooldown == 9.0
    assert w._warmup == 42.0


def test_build_watchdog_enabled_by_default():
    w = wd.build_watchdog({}, ServiceRegistry())
    assert w is not None and w._base == MONITOR_OMNI_URL
    assert w._warmup == MONITOR_OMNI_WARMUP_S


def test_build_watchdog_disabled_returns_none():
    got = wd.build_watchdog({"omni_enabled": False}, ServiceRegistry())
    assert got is None
