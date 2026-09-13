"""Тесты хранилища статусов (StatusStore)."""

import json
import sys
import tempfile
import os
from unittest.mock import MagicMock

from lib.status import StatusStore, BUILTIN_CHECKERS, _check_vpn


def _write_status_file(defs):
    """Создаёт временный status.json, возвращает путь."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"statuses": defs}, f)
    return path


class TestStatusStoreLoading:
    """Загрузка и базовое состояние."""

    def test_missing_file_disabled(self, tmp_path):
        """Без файла хранилище выключено, всё неактивно."""
        store = StatusStore(str(tmp_path / "nonexistent.json"))
        assert store.enabled is False
        assert store.is_active("vpn") is False
        assert store.snapshot() == {}
        assert store.ensure(["vpn"]) == []

    def test_load_definitions(self):
        """Определения загружаются, начальное состояние False."""
        path = _write_status_file({
            "vpn": {"checker": "vpn"},
            "custom": {"check": "exit 0"},
        })
        try:
            store = StatusStore(path)
            assert store.enabled is True
            assert store.is_active("vpn") is False
            assert store.snapshot() == {"vpn": False, "custom": False}
        finally:
            os.unlink(path)

    def test_unknown_status_inactive(self):
        """Неизвестный статус всегда неактивен."""
        path = _write_status_file({"vpn": {"checker": "vpn"}})
        try:
            store = StatusStore(path)
            assert store.is_active("ghost") is False
        finally:
            os.unlink(path)

    def test_path_for_commands_file(self):
        """Путь к status.json выводится из пути commands.json."""
        import os
        assert StatusStore.path_for_commands_file(
            os.path.join("x", "targets", "HOST", "commands.json")
        ) == os.path.join("x", "targets", "HOST", "status.json")

    def test_need_message_default_and_custom(self):
        """need_message: кастомное или дефолтное."""
        path = _write_status_file({
            "vpn": {"checker": "vpn", "need_message": "Включи VPN вручную"},
            "media": {"checker": "media"},
        })
        try:
            store = StatusStore(path)
            assert store.need_message("vpn") == "Включи VPN вручную"
            assert store.need_message("media") == "Нужен статус: media"
        finally:
            os.unlink(path)


class TestStatusStoreChecks:
    """Выполнение проверок."""

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
        path = _write_status_file({"vpn": {"checker": "vpn"}})
        try:
            mock_fn = mocker.patch.dict(
                "lib.status.BUILTIN_CHECKERS", {"vpn": lambda: True})
            store = StatusStore(path)
            assert store.refresh("vpn") is True
            assert mock_fn is not None
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
        path = _write_status_file({"vpn": {"checker": "vpn"}})
        try:
            store = StatusStore(path)
            store.set("vpn", True)
            assert store.is_active("vpn") is True
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
        orig = status_mod.BUILTIN_CHECKERS.get("vpn")
        status_mod.BUILTIN_CHECKERS["vpn"] = _checker
        path = _write_status_file({"vpn": {"checker": "vpn"}})
        try:
            store = StatusStore(path)
            assert store.ensure(["vpn"]) == ["vpn"]
            assert store.ensure(["vpn"]) == []
        finally:
            if orig is None:
                del status_mod.BUILTIN_CHECKERS["vpn"]
            else:
                status_mod.BUILTIN_CHECKERS["vpn"] = orig
            os.unlink(path)


class TestStatusStoreThread:
    """Фоновый опрос."""

    def test_start_stop_polling(self):
        """Поток опрашивает и останавливается."""
        cmd = f'\"{sys.executable}\" -c \"import sys; sys.exit(0)\"'
        path = _write_status_file({"ok": {"check": cmd, "interval": 0.1}})
        try:
            store = StatusStore(path, default_interval=0.1)
            store.start()
            for _ in range(100):
                if store.is_active("ok"):
                    break
                import time
                time.sleep(0.05)
            assert store.is_active("ok") is True
            thread = store._thread
            assert thread is not None
            store.stop()
            assert thread.is_alive() is False
        finally:
            os.unlink(path)

    def test_start_disabled_no_thread(self, tmp_path):
        """Без файла поток не запускается."""
        store = StatusStore(str(tmp_path / "none.json"))
        store.start()
        assert store._thread is None


class TestBuiltinCheckers:
    """Реестр встроенных проверок."""

    def test_registry_has_expected(self):
        """Все четыре чекера зарегистрированы и вызываемы."""
        for name in ("vpn", "media", "browser", "browser_youtube"):
            assert name in BUILTIN_CHECKERS
            assert callable(BUILTIN_CHECKERS[name])

    def test_check_vpn_unreachable_is_false(self, mocker):
        """Недоступный youtube даёт False."""
        mocker.patch("urllib.request.urlopen",
                     side_effect=Exception("down"))
        assert _check_vpn() is False
