"""Скорость проверок статусов: что платит пользователь за блокировку.

ensure()/missing_requires() синхронно перепроверяют выключенные статусы
в момент команды: TCP-коннект (proxy), запуск PowerShell (media),
HTTP к CDP (browser). Замеры живые — это реальные задержки речи.
"""

import platform

import pytest

from lib.runtime.status import StatusStore
from lib.runtime.status_checkers import (
    _check_browser,
    _check_browser_youtube,
    _check_media,
    _check_media_session,
    _check_proxy,
)
from lib.voice_cmd.commands import CommandMatcher
from lib.voice_cmd.config_loader import get_device_commands_path


def _store() -> StatusStore:
    path = StatusStore.path_for_commands_file(
        get_device_commands_path(platform.node()))
    return StatusStore(path)


def _require_store():
    store = _store()
    if not store.enabled:
        pytest.skip("для этого устройства нет status.json")
    return store


def _force_all_off(store: StatusStore, touch_checks: bool = True) -> None:
    """Сбрасывает все статусы в False — худший случай для ensure().

    touch_checks=False оставляет отметки времени проверок свежими:
    «фон опросил, всё выключено» — сценарий для TTL-пути.
    """
    with store._lock:
        for name in store._states:
            store._states[name] = False
        if touch_checks:
            for name in store._last_check:
                store._last_check[name] = 0.0


class TestCheckersSpeed:
    """Каждая встроенная проверка по отдельности."""

    def test_proxy(self, bench):
        bench.record("checker.proxy", _check_proxy, runs=3)

    def test_media(self, bench):
        bench.record("checker.media", _check_media, runs=3)

    def test_media_session(self, bench):
        bench.record("checker.media_session", _check_media_session, runs=3)

    def test_browser(self, bench):
        bench.record("checker.browser", _check_browser, runs=3)

    def test_browser_youtube(self, bench):
        bench.record("checker.browser_youtube", _check_browser_youtube,
                     runs=3)


class TestEnsureSpeed:
    """Пути блокировки команды: ensure() и missing_requires()."""

    def test_ensure_all_off(self, bench):
        """Худший случай: команда требует все статусы, все выключены."""
        store = _require_store()
        names = list(store._defs)

        def _worst():
            _force_all_off(store)
            store.ensure(names)

        bench.record("status.ensure_all_off", _worst, runs=3)

    def test_ensure_fresh_off(self, bench):
        """ensure() со СВЕЖИМИ результатами опроса: фон уже всё проверил.

        Штатный сценарий запущенного приложения: статусы выключены,
        но последняя проверка была только что. Сейчас это полный
        повтор всех проверок; с TTL должно стать ~0.
        """
        store = _require_store()
        names = list(store._defs)
        store.refresh_all()  # свежие _last_check, реальные значения не важны

        def _fresh_off():
            _force_all_off(store, touch_checks=False)
            store.ensure(names)

        bench.record("status.ensure_fresh_off", _fresh_off, runs=3)

    def test_missing_requires_worst(self, bench):
        """missing_requires команды с максимальным числом requires."""
        store = _require_store()
        matcher = CommandMatcher(
            get_device_commands_path(platform.node()), status_store=store)
        requires = matcher.requires_map()
        if not requires:
            pytest.skip("в commands.json нет requires")
        cmd_id = max(requires, key=lambda k: len(requires[k]))

        def _worst():
            _force_all_off(store)
            matcher.missing_requires(cmd_id)

        bench.record("status.missing_requires_worst", _worst, runs=3)

    def test_is_active_hot(self, bench):
        """Чтение кэшированного статуса (цена «быстрого» пути)."""
        store = _require_store()
        names = list(store._defs)
        bench.record("status.is_active_hot",
                     lambda: [store.is_active(n) for n in names], runs=50)
