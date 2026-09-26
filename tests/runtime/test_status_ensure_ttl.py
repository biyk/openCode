"""Юнит-тесты негативного TTL в StatusStore.ensure().

Свежий результат фонового опроса не должен перепроверяться синхронно
в момент команды (замерено: до ~6 с на заблокированной команде).
"""

import json
import os
import tempfile

from lib.runtime.status import StatusStore


def _write_status_file(defs):
    """Создаёт временный status.json, возвращает путь."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"statuses": defs}, f)
    return path


class TestEnsureTtl:
    """ensure(): fresh-проверка не дублируется, протухшая — перепроверяется."""

    def setup_method(self):
        import lib.runtime.status as status_mod
        self._mod = status_mod
        self._orig = dict(status_mod.BUILTIN_CHECKERS)
        self.path = None

    def teardown_method(self):
        self._mod.BUILTIN_CHECKERS.clear()
        self._mod.BUILTIN_CHECKERS.update(self._orig)
        if self.path and os.path.exists(self.path):
            os.unlink(self.path)

    def _store(self, checker, **kwargs):
        """Хранилище с единственным статусом «x» на данном чекере."""
        self.path = _write_status_file({"x": {"checker": "x"}})
        self._mod.BUILTIN_CHECKERS["x"] = checker
        return StatusStore(self.path, **kwargs)

    def test_second_ensure_skips_recent_check(self):
        """Второй ensure подряд не зовёт чекер: результат ещё свежий."""
        calls = []
        store = self._store(lambda: calls.append(1) or False)
        assert store.ensure(["x"]) == ["x"]
        assert store.ensure(["x"]) == ["x"]
        assert len(calls) == 1

    def test_stale_status_rechecked(self):
        """После «протухания» отметки чекер зовётся снова."""
        calls = []
        store = self._store(lambda: calls.append(1) or False)
        store.ensure(["x"])
        store._last_check["x"] = 0.0
        assert store.ensure(["x"]) == ["x"]
        assert len(calls) == 2

    def test_zero_ttl_always_rechecks(self):
        """recheck_ttl=0 возвращает старое поведение (перепроверка всегда)."""
        calls = []
        store = self._store(
            lambda: calls.append(1) or False, recheck_ttl=0.0)
        store.ensure(["x"])
        store.ensure(["x"])
        assert len(calls) == 2

    def test_active_status_never_ensured(self):
        """Активный статус ensure не проверяет и не блокирует."""
        calls = []
        store = self._store(lambda: calls.append(1) or True)
        assert store.ensure(["x"]) == []
        assert len(calls) == 1

    def test_ttl_refreshes_state_on_stale_check(self):
        """Протухший статус, ставший активным, снимается с блокировки."""
        calls = []

        def _checker():
            calls.append(1)
            return len(calls) >= 2

        store = self._store(_checker)
        assert store.ensure(["x"]) == ["x"]
        store._last_check["x"] = 0.0
        assert store.ensure(["x"]) == []
        assert store.is_active("x") is True
