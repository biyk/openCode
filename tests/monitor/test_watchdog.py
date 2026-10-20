"""Тесты таблицы решений смотрителя OmniRouter (`lib/monitor/watchdog.py`).

Живого процесса и CLI нет: подменяются проба здоровья, порт, число соединений,
pid-файл и рестартер. Проверяется главное из правил надзора — молчание пробы НЕ
достаточный повод убивать шлюз. Сама лестница бэк-оффа — в test_policy.py,
прогрев — в test_watchdog_warmup.py (лимит 200 строк, §9).
"""
import inspect

from lib.monitor import watchdog as wd
from lib.monitor.policy import RestartPolicy
from lib.monitor.registry import ERROR, IDLE, WORKING, ServiceRegistry
from lib.monitor.tuning import (MONITOR_OMNI_HANG_AFTER_S,
                                MONITOR_OMNI_HANG_FAILS, MONITOR_OMNI_URL,
                                MONITOR_OMNI_WARMUP_S, MONITOR_WATCHDOG_S)


class _Wd(wd.OmniWatchdog):
    """Смотритель с заранее известными ответами проб, рестартера и реестра."""

    def __init__(self, health=None, listening=None, connections=None,
                 running=None, restarter=None, **kw):
        self.events = []
        self.restarts = []
        kw.setdefault("hang_after_s", 0.0)        # «завис» проверяем сразу
        kw.setdefault("policy", RestartPolicy(backoff=(0,), budget=99,
                                              window_s=3600))
        super().__init__(ServiceRegistry(),
                         health=health or (lambda base: True),
                         listening=listening or (lambda base: True),
                         connections=connections or (lambda port: 0),
                         running=running or (lambda: False),
                         restarter=restarter or self._ok, **kw)

    def _ok(self, port, drain):
        self.restarts.append((port, drain))
        return True, f"ok:{port}"

    def _report(self, state, detail=""):
        self.events.append((state, detail))
        super()._report(state, detail)

    def row(self):
        return self._registry.snapshot().get(wd.SERVICE_ID, {})


def test_healthy_is_green_and_resets_fails():
    w = _Wd(health=lambda base: True)
    w._fails, w._since = 2, 1.0
    assert w.tick() == "up"
    assert w._fails == 0
    assert w._since is None
    assert w.row()["state"] == WORKING


def test_dead_port_is_raised_without_stop():
    """Порт закрыт → процесс завершился сам. `stop` не зовём: дренажить нечего."""
    w = _Wd(health=lambda base: False, listening=lambda base: False)
    assert w.tick() == "restarted"
    assert w.restarts == [(20128, False)]
    assert w.row()["state"] == WORKING
    assert "не запущен" in w.row()["detail"]


def test_dead_port_with_live_pid_drains_first():
    """Порта нет, но демон из pid-файла жив — его просят завершиться мягко."""
    w = _Wd(health=lambda base: False, listening=lambda base: False,
            running=lambda: True)
    assert w.tick() == "restarted"
    assert w.restarts == [(20128, True)]


def test_silence_below_the_window_is_not_a_hang():
    """Регресс трёхминутного цикла: 90 с молчания — это занятый шлюз.

    Замерено: один штатный auto/smart-запрос глушит /healthz на 40–170 с,
    поэтому «завис» решается только по длительному молчанию, а не по трём
    пропущенным пробам.
    """
    w = _Wd(health=lambda base: False, listening=lambda base: True,
            hang_fails=3, hang_after_s=300)
    assert w.tick() == "degraded"
    assert w.tick() == "degraded"
    assert w.tick() == "degraded"          # три неудачи подряд — и всё ещё ждём
    assert w.restarts == []
    assert w.row()["state"] == IDLE
    assert "из 300" in w.row()["detail"]


def test_long_silence_and_idle_port_is_a_hang():
    w = _Wd(health=lambda base: False, listening=lambda base: True,
            hang_fails=2, hang_after_s=0.0)
    assert w.tick() == "degraded"
    assert w.tick() == "restarted"
    assert w.restarts == [(20128, True)]   # процесс жив → сначала stop с дренажом
    assert "завис" in w.row()["detail"]


def test_requests_in_flight_are_never_interrupted():
    """Молчит долго, но на порту есть соединения → не убиваем (правило 8).

    Рестарт режет стрим, клиент получает 499; раньше этот случай и был
    «зависшим» — смотритель сам обрывал наши же длинные запросы.
    """
    w = _Wd(health=lambda base: False, listening=lambda base: True,
            connections=lambda port: 2, hang_fails=1, hang_after_s=0.0)
    assert w.tick() == "busy"
    assert w.restarts == []
    assert w.row()["state"] == ERROR
    assert "идут запросы (2)" in w.row()["detail"]


def test_unknown_connections_do_not_justify_a_kill():
    """netstat не ответил — это «не знаем», а не «простаивает»."""
    w = _Wd(health=lambda base: False, listening=lambda base: True,
            connections=lambda port: None, hang_fails=1, hang_after_s=0.0)
    assert w.tick() == "unknown"
    assert w.restarts == []
    assert w.row()["state"] == ERROR
    assert "не посчитать" in w.row()["detail"]


def test_restart_failure_is_red_not_exception():
    w = _Wd(health=lambda base: False, listening=lambda base: False,
            restarter=lambda port, drain: (False, "CLI omniroute не найден"))
    assert w.tick() == "failed"
    assert w.row()["state"] == ERROR
    assert "не найден" in w.row()["detail"]


def test_probe_crash_does_not_raise_out_of_tick():
    def _boom(base):
        raise RuntimeError("метр не ответил")

    w = _Wd(health=_boom)
    assert w.tick() == "error"          # вердикт вместо исключения


def test_backoff_delays_the_next_restart():
    """Правило 5: после перезапуска пауза растёт — второй волны сразу нет."""
    pol = RestartPolicy(backoff=(30,), budget=99, window_s=3600)
    pol.on_attempt()
    w = _Wd(health=lambda base: False, listening=lambda base: True,
            hang_fails=1, warmup_s=0.0, policy=pol)
    assert w.tick() == "backoff"        # 30 с бэк-оффа ещё не истекли
    assert w.restarts == []


def test_budget_exhaustion_calls_a_human_not_more_restarts():
    """Правило 5: бюджет бит — руки прочь, оповещение (один раз)."""
    told = []
    pol = RestartPolicy(backoff=(0,), budget=1, window_s=3600)
    pol.on_attempt()
    w = _Wd(health=lambda base: False, listening=lambda base: False,
            policy=pol, notifier=told.append)
    assert w.tick() == "budget"
    assert w.restarts == []
    assert w.row()["state"] == ERROR
    assert told and "нужен человек" in told[0]
    assert w.tick() == "budget"
    assert len(told) == 1               # не строчить консоль каждый такт


def test_health_recovered_before_the_kill_cancels_it():
    """Оглядка: пока решали «завис», шлюз ожил — убиваем уже здорового? Нет."""
    answers = iter([False, True])       # проба в начале tick, затем оглядка
    w = _Wd(health=lambda base: next(answers), listening=lambda base: True,
            hang_fails=1, hang_after_s=0.0)
    assert w.tick() == "up"             # вердикт отдан оглядкой
    assert w.restarts == []             # restarter не позван
    assert w.row()["state"] == WORKING


def test_up_detail_recognizes_our_own_restart():
    w = _Wd(health=lambda base: True)
    w._policy.on_attempt()
    assert w.tick() == "up"
    assert "поднят смотрителем" in w.row()["detail"]
    w._policy.on_healthy()
    assert w.tick() == "up"
    assert w.row()["detail"] == MONITOR_OMNI_URL


def test_defaults_come_from_tuning():
    p = inspect.signature(wd.OmniWatchdog.__init__).parameters
    assert p["base_url"].default == MONITOR_OMNI_URL
    assert p["interval_s"].default == MONITOR_WATCHDOG_S
    assert p["hang_fails"].default == MONITOR_OMNI_HANG_FAILS
    assert p["hang_after_s"].default == MONITOR_OMNI_HANG_AFTER_S
    assert p["warmup_s"].default == MONITOR_OMNI_WARMUP_S
    assert wd.SERVICE_ID == "omniroute"
    # Интервал 30 с и потолок молчания дольше «трёх неудач» — иначе вернёмся к
    # прежнему циклу: проба под нагрузкой не успевает отличить занятой шлюз.
    assert MONITOR_WATCHDOG_S >= 30.0
    assert MONITOR_OMNI_HANG_AFTER_S > MONITOR_WATCHDOG_S * MONITOR_OMNI_HANG_FAILS
