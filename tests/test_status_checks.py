"""Тесты хранилища статусов: выполнение проверок."""


import json
import sys
import tempfile
import os
from unittest.mock import MagicMock
from lib.status import StatusStore


def _write_status_file(defs):
    """Создаёт временный status.json, возвращает путь."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"statuses": defs}, f)
    return path


class TestStatusStoreChecks:
    """Shell/checker проверки, анонсы, ensure."""

    def test_shell_check_success(self):
        """Shell-проверка с кодом 0 даёт True."""
        cmd = f'\"{sys.executable}\" -c \"import sys; sys.exit(0)\"'
        path = _write_status_file({"ok": {"check": cmd}})
        try:
            store = StatusStore(path)
            assert store.refresh("ok") is True
            assert store.is_active("ok") is True
        finally:
            os.unlink(path)

    def test_shell_check_failure(self):
        """Shell-проверка с ненулевым кодом даёт False."""
        cmd = f'\"{sys.executable}\" -c \"import sys; sys.exit(1)\"'
        path = _write_status_file({"bad": {"check": cmd}})
        try:
            store = StatusStore(path)
            assert store.refresh("bad") is False
            assert store.is_active("bad") is False
        finally:
            os.unlink(path)

    def test_shell_check_per_os(self, mocker):
        """Проверка выбирается по платформе."""
        cmd = f'\"{sys.executable}\" -c \"import sys; sys.exit(0)\"'
        path = _write_status_file({"os": {"check": {"windows": cmd}}})
        try:
            mocker.patch("lib.status.platform.system", return_value="Windows")
            store = StatusStore(path)
            assert store.refresh("os") is True
        finally:
            os.unlink(path)

    def test_builtin_checker_called(self, mocker):
        """Встроенный checker вызывается по имени."""
        path = _write_status_file({"proxy": {"checker": "proxy"}})
        try:
            mock_fn = mocker.patch.dict(
                "lib.status.BUILTIN_CHECKERS", {"proxy": lambda: True})
            store = StatusStore(path)
            assert store.refresh("proxy") is True
            assert mock_fn is not None
        finally:
            os.unlink(path)

    def test_checker_receives_config(self, mocker):
        """checker_config передаётся чекеру аргументом."""
        received = {}

        def _proxy_checker(config):
            received["config"] = config
            return config.get("port") == 1080

        path = _write_status_file({
            "proxy": {
                "checker": "proxy",
                "checker_config": {"host": "192.168.1.107", "port": 1080},
            }
        })
        try:
            mocker.patch.dict(
                "lib.status.BUILTIN_CHECKERS", {"proxy": _proxy_checker})
            store = StatusStore(path)
            assert store.refresh("proxy") is True
            assert received == {"config": {"host": "192.168.1.107", "port": 1080}}
        finally:
            os.unlink(path)

    def test_unknown_checker_is_false(self):
        """Неизвестный checker даёт False без падения."""
        path = _write_status_file({"x": {"checker": "nope"}})
        try:
            store = StatusStore(path)
            assert store.refresh("x") is False
        finally:
            os.unlink(path)

    def test_checker_exception_is_false(self, mocker):
        """Исключение в checker превращается в False."""
        path = _write_status_file({"x": {"checker": "boom"}})
        try:
            mocker.patch.dict(
                "lib.status.BUILTIN_CHECKERS",
                {"boom": lambda: 1 / 0})
            store = StatusStore(path)
            assert store.refresh("x") is False
        finally:
            os.unlink(path)

    def test_no_check_spec_is_false(self):
        """Статус без checker/check всегда False."""
        path = _write_status_file({"x": {"description": "пустой"}})
        try:
            store = StatusStore(path)
            assert store.refresh("x") is False
        finally:
            os.unlink(path)

    def test_title_updated_on_change(self, mocker):
        """При смене статуса обновляется заголовок окна (Windows)."""
        import sys as _sys
        mocker.patch.object(_sys, "platform", "win32")
        mock_system = mocker.patch("os.system")
        cmd = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
        path = _write_status_file({"ok": {"check": cmd}})
        try:
            store = StatusStore(path)
            store.refresh("ok")
            assert mock_system.call_count == 1
            title = mock_system.call_args[0][0]
            assert title.startswith("title Voice:")
            assert "ok=on" in title
        finally:
            os.unlink(path)

    def test_title_not_updated_without_change(self, mocker):
        """Без смены статуса заголовок не трогают."""
        mock_system = mocker.patch("os.system")
        cmd = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
        path = _write_status_file({"ok": {"check": cmd}})
        try:
            store = StatusStore(path)
            store.refresh("ok")
            store.refresh("ok")
            assert mock_system.call_count <= 1
        finally:
            os.unlink(path)

    def test_change_announced_once(self):
        """Переход состояния печатается, повтор — нет."""
        cmd = f'\"{sys.executable}\" -c \"import sys; sys.exit(0)\"'
        path = _write_status_file({"ok": {"check": cmd}})
        try:
            output = MagicMock()
            store = StatusStore(path, output=output)
            store.refresh("ok")
            assert output.print_info.call_count == 1
            assert "[Status]" in output.print_info.call_args[0][0]
            store.refresh("ok")
            assert output.print_info.call_count == 1
        finally:
            os.unlink(path)

    def test_set_marks_known_only(self):
        """set() ставит только известные статусы."""
        path = _write_status_file({"proxy": {"checker": "proxy"}})
        try:
            store = StatusStore(path)
            store.set("proxy", True)
            assert store.is_active("proxy") is True
            store.set("ghost", True)
            assert store.is_active("ghost") is False
        finally:
            os.unlink(path)

    def test_ensure_refreshes_when_off(self):
        """ensure() синхронно перепроверяет выключенные."""
        calls = []

        def _checker():
            calls.append(1)
            return len(calls) >= 2

        import lib.status as status_mod
        orig = status_mod.BUILTIN_CHECKERS.get("proxy")
        status_mod.BUILTIN_CHECKERS["proxy"] = _checker
        path = _write_status_file({"proxy": {"checker": "proxy"}})
        try:
            store = StatusStore(path)
            assert store.ensure(["proxy"]) == ["proxy"]
            assert store.ensure(["proxy"]) == []
        finally:
            if orig is None:
                del status_mod.BUILTIN_CHECKERS["proxy"]
            else:
                status_mod.BUILTIN_CHECKERS["proxy"] = orig
            os.unlink(path)
