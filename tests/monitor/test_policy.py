# TOOLTIP: Тесты политики перезапусков: растущий бэк-офф, скользящий бюджет, сброс по здоровью
"""Тесты политики перезапусков (`lib/monitor/policy.py`).

Именно её не хватало, чтобы смотритель перестал перезапускать шлюз каждые
3 минуты: пауза обязана РАСТИ с каждой неудачей, а при исчерпании бюджета —
кончаться совсем (докладывать человеку). Время подаётся часами, sleep не нужен.
"""
from lib.monitor.policy import RestartPolicy


class _Clock:
    """Ручные часы: `advance` перематывает время, вызов — отдаёт его."""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _policy(**kw):
    clock = _Clock()
    return RestartPolicy(clock=clock, **kw), clock


def test_first_restart_needs_no_wait():
    p, _ = _policy(backoff=(1, 2, 5, 15, 60))
    assert p.wait_s() == 0.0
    assert not p.exhausted()


def test_backoff_grows_with_each_attempt():
    p, clock = _policy(backoff=(1, 2, 5), budget=99, window_s=3600)
    p.on_attempt()
    assert p.wait_s() == 1.0
    clock.advance(0.5)
    assert p.wait_s() == 0.5
    clock.advance(0.5)
    assert p.wait_s() == 0.0
    p.on_attempt()                      # вторая ступень — уже 2 с
    assert p.wait_s() == 2.0
    p.on_attempt()                      # третья — 5 с
    assert p.wait_s() == 5.0
    p.on_attempt()                      # потолок: дальше не растёт
    assert p.wait_s() == 5.0


def test_healthy_resets_the_ladder():
    p, clock = _policy(backoff=(1, 30), budget=99, window_s=3600)
    p.on_attempt()
    clock.advance(10)
    p.on_healthy()
    assert p.wait_s() == 0.0
    p.on_attempt()                      # снова первая ступень, не вторая
    assert p.wait_s() == 1.0
    assert p.step() == 1


def test_budget_stops_restarts_in_window():
    p, _ = _policy(backoff=(0,), budget=3, window_s=600)
    for _ in range(3):
        p.on_attempt()
    assert p.restarts() == 3
    assert p.exhausted()


def test_budget_window_slides():
    """За окном попытки забываются: процессу, пожившему, дают новый бюджет."""
    p, clock = _policy(backoff=(0,), budget=2, window_s=600)
    p.on_attempt()
    clock.advance(300)
    p.on_attempt()
    assert p.exhausted()
    clock.advance(299)                  # первой попытке 599 с — обе в окне
    assert p.exhausted()
    clock.advance(2)                    # первая вышла за окно
    assert not p.exhausted()
    assert p.restarts() == 1


def test_budget_of_one_is_not_zero():
    """budget=0 — конфиг-ловушка: минимум 1, иначе сервис не поднять никогда."""
    p, _ = _policy(budget=0, window_s=600)
    assert p.budget == 1
    p.on_attempt()
    assert p.exhausted()


def test_since_attempt_reports_age_of_last_restart():
    p, clock = _policy(backoff=(1, 2))
    assert p.since_attempt() is None
    p.on_attempt()
    clock.advance(30)
    assert p.since_attempt() == 30.0
    p.on_healthy()
    assert p.since_attempt() is None


def test_from_config_defaults_to_tuning():
    p = RestartPolicy.from_config({})
    assert p.budget == 5
    assert p.window_s == 600.0
    assert p.wait_s() == 0.0
    p.on_attempt()
    # настоящие часы: ступень 1 с уже частично истекла
    assert 0.5 <= p.wait_s() <= 1.0


def test_from_config_reads_device_section():
    p = RestartPolicy.from_config({"omni_backoff_s": [3, 9],
                                   "omni_budget_restarts": 2,
                                   "omni_budget_window_s": 120})
    assert p.budget == 2
    assert p.window_s == 120.0
    p.on_attempt()
    assert 2.5 <= p.wait_s() <= 3.0      # лестница из конфига, не дефолт
