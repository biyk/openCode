"""Тесты хранилища статусов: загрузка и реестр."""


import json
import tempfile
import os
from lib.status import StatusStore, BUILTIN_CHECKERS
from lib.status_checkers import _check_vpn


def _write_status_file(defs):
    """Создаёт временный status.json, возвращает путь."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"statuses": defs}, f)
    return path


class TestStatusStoreLoading:
    """Файл статусов, need_message."""

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


class TestBuiltinCheckers:
    """Реестр встроенных проверок."""

    def test_registry_has_expected(self):
        """Все четыре чекера зарегистрированы и вызываемы."""
        for name in ("vpn", "media", "media_session", "browser",
                     "browser_youtube"):
            assert name in BUILTIN_CHECKERS
            assert callable(BUILTIN_CHECKERS[name])

    def test_check_vpn_unreachable_is_false(self, mocker):
        """Недоступный youtube даёт False."""
        mocker.patch("urllib.request.urlopen",
                     side_effect=Exception("down"))
        assert _check_vpn() is False
