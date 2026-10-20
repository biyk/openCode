"""Тесты прогрева OmniRouter смотрителем (`lib/monitor/watchdog.py`).

Отдельный файл от test_watchdog.py (лимит 200 строк на файл, §9): здесь только
ветка `warmup_s` — пауза после нашего рестарта, во время которой открытый порт
без ответа `/healthz` не считается зависанием. Решает прогрев не часы, а первый
200 (правило 6): он снимается пробой `_on_up`, а `since_attempt` лишь ограничивает
паузу, по истечении которой молчание снова коится в «завис».
"""
import time

from lib.monitor import watchdog as wd
from lib.monitor.policy import RestartPolicy
from lib.monitor.registry import IDLE, ServiceRegistry


class _Warm(wd.OmniWatchdog):
    """Смотритель с заранее известными ответами проб и считающим рестартером.

    Метод называется НЕ `_restart`: так зовётся внутренний шаг смотрителя, и
    одноимённая перезапись вернула бы кортеж вместо вердикта.
    """

    def __init__(self, health, listening, **kw):
        self.calls = []
        kw.setdefault("policy",
                      RestartPolicy(backoff=(0,), budget=99, window_s=3600))
        kw.setdefault("hang_after_s", 0.0)      # «завис» считаем сразу
        super().__init__(ServiceRegistry(), health=health,
                         listening=listening,
                         connections=lambda port: 0, running=lambda: False,
                         restarter=self._stub, **kw)

    def _stub(self, port, drain):
        self.calls.append((port, drain))
        return True, "ok"

    def row(self):
        return self._registry.snapshot().get(wd.SERVICE_ID, {})


def _dead(base):
    return False


def _alive(base):
    return True


def test_warmup_after_restart_is_not_a_hang():
    """Регресс: порт открыт сразу, /healthz отвечает только через ~45 с.

    До паузы на подъём такты успевали накопиться на ещё греющемся сервере,
    и смотритель убивал его как висячий — рестарт по кругу, в котором
    прокси не доживает до готовности.
    """
    w = _Warm(_dead, lambda base: False, hang_fails=3, warmup_s=120)
    assert w.tick() == "restarted"      # подняли: порт ещё не слушает
    w._listening = _alive               # сервер занял порт…
    for _ in range(6):                   # …а здоровье молчит 90 с из 120
        assert w.tick() == "warmup"
    assert w.calls == [(20128, False)]   # второго рестарта не было
    assert w._fails == 0
    assert w.row()["state"] == IDLE
    assert "греется" in w.row()["detail"]


def test_warmup_expiry_restores_hang_detection():
    """Прогрев закончился — открытый порт без ответа снова «завис»."""
    w = _Warm(_dead, _alive, hang_fails=2, warmup_s=60)
    w._policy.on_attempt()
    assert w.tick() == "warmup"
    w._policy._last = time.time() - 61   # пауза на подъём истекла
    assert w.tick() == "degraded"
    assert w.tick() == "restarted"
    assert w.calls[-1] == (20128, True)  # процесс жив → сначала дренаж


def test_dead_port_is_raised_during_warmup():
    """Прогрев не прикрывает мёртвый порт: процесс упал — поднимаем сразу."""
    w = _Warm(_dead, lambda base: False, warmup_s=120)
    assert w.tick() == "restarted"
    assert w.tick() == "restarted"
    assert len(w.calls) == 2


def test_warmup_never_blocks_a_healthy_server():
    """Здоровье ответило в ходе прогрева — сразу зелёный, без ожидания."""
    w = _Warm(_alive, _alive, warmup_s=120)
    w._policy.on_attempt()
    assert w.tick() == "up"
    assert "поднят смотрителем" in w.row()["detail"]
