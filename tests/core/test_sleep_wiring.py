# TOOLTIP: Тесты обвязки гейта «СОН»: порядок в tick, mute в боте, статус в конфиге
"""Обвязка правила §4.3 («СОН» снимает уведомления и сообщения»).

Логику проверяют профильные тесты (test_sleep_gate, test_task_monitor_sleep,
test_bot_mute). Здесь — тихие потери, которые иначе не поймать ничем:
монитор спрашивает сон ДО оповещения о переработке, бот подставлял бы mute,
но не reply, при запуске сон не проверяется (вердикт — только в цикле),
статус `sleeping` объявлен (иначе фоновый опрос его не обновляет),
а фабрики передают гейт в монитор и в бота.
"""

import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _source(*parts) -> str:
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


def _method(src: str, name: str) -> str:
    """Тело метода до следующего `def` — чтобы гейт искался именно в нём."""
    body = src[src.index(f"def {name}("):]
    nxt = body.find("\n    def ", 1)
    return body if nxt < 0 else body[:nxt]


class TestMonitorOrder:
    def test_sleep_checked_before_overtime(self):
        """Иначе оповещение о переработке ушло бы спящему пользователю."""
        src = _source("lib", "core", "task_monitor.py")
        body = src[src.index("def tick("):]
        assert body.index("_sleeping()") < body.index("self._overtime.check")

    def test_reply_is_not_the_muted_path(self):
        """Гейт стоит на broadcast/offer; `reply` остаётся доступным ночью."""
        src = _source("lib", "telegram", "bot.py")
        for name in ("broadcast", "offer"):
            assert "muted(" in _method(src, name), name
        assert "muted(" not in _method(src, "reply")


class TestWiring:
    def test_main_mutes_telegram_without_startup_probe(self):
        """Бот подписан на гейт, но при запуске сон НЕ проверяется (§4.3)."""
        src = _source("main.py")
        assert re.search(r"mute=is_sleeping", src), "бот не подписан на гейт"
        for banned in ("warm_sleep(", "check_sleeping("):
            assert banned not in src, f"{banned} при старте — сон в цикле"

    def test_monitor_gets_gate_verdict(self):
        assert "sleep_fn=check_sleeping" in _source(
            "lib", "core", "task_monitor_launch.py")

    def test_status_checker_is_registered(self):
        from lib.runtime.status import BUILTIN_CHECKERS
        assert "sleep" in BUILTIN_CHECKERS

    def test_device_declares_sleeping_status(self):
        """Без записи в status.json хранилище его не опрашивает и не хранит."""
        path = os.path.join(REPO, "targets", "FLTP-5i3-16512", "status.json")
        if not os.path.isfile(path):
            return                              # чужой ПК: свой конфиг
        with open(path, encoding="utf-8") as fh:
            spec = json.load(fh)["statuses"]["sleeping"]
        assert spec["checker"] == "sleep"
        assert "СОН" in spec["description"]


class TestSleepChecker:
    def test_checker_reads_the_gate(self, mocker):
        """Чекер статуса — тонкая обёртка над гейтом, без своей логики."""
        from lib.runtime.status_checkers import _check_sleep
        check = mocker.patch("lib.core.sleep_gate.check_sleeping",
                             return_value=True)
        assert _check_sleep() is True
        check.assert_called_once_with()

    def test_checker_failure_is_not_sleeping(self, mocker):
        mocker.patch("lib.core.sleep_gate.check_sleeping",
                     side_effect=OSError("нет токена"))
        from lib.runtime.status_checkers import _check_sleep
        assert _check_sleep() is False
