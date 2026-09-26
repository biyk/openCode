"""Тесты хранилища статусов: загрузка и реестр."""


import json
import tempfile
import os
from lib.runtime.status import StatusStore, BUILTIN_CHECKERS
from lib.runtime.status_checkers import _check_proxy


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
        assert store.is_active("proxy") is False
        assert store.snapshot() == {}
        assert store.ensure(["proxy"]) == []

    def test_load_definitions(self):
        """Определения загружаются, начальное состояние False."""
        path = _write_status_file({
            "proxy": {"checker": "proxy"},
            "custom": {"check": "exit 0"},
        })
        try:
            store = StatusStore(path)
            assert store.enabled is True
            assert store.is_active("proxy") is False
            assert store.snapshot() == {"proxy": False, "custom": False}
        finally:
            os.unlink(path)

    def test_unknown_status_inactive(self):
        """Неизвестный статус всегда неактивен."""
        path = _write_status_file({"proxy": {"checker": "proxy"}})
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
            "proxy": {"checker": "proxy",
                      "need_message": "Проверь доступность прокси"},
            "media": {"checker": "media"},
        })
        try:
            store = StatusStore(path)
            assert store.need_message("proxy") == "Проверь доступность прокси"
            assert store.need_message("media") == "Нужен статус: media"
        finally:
            os.unlink(path)


class TestBuiltinCheckers:
    """Реестр встроенных проверок."""

    def test_registry_has_expected(self):
        """Все чекеры зарегистрированы и вызываемы."""
        for name in ("proxy", "media", "media_session", "browser",
                     "browser_youtube"):
            assert name in BUILTIN_CHECKERS
            assert callable(BUILTIN_CHECKERS[name])

    def test_check_proxy_unreachable_is_false(self, mocker):
        """Недоступный прокси даёт False."""
        mocker.patch("socket.create_connection",
                     side_effect=OSError("down"))
        assert _check_proxy() is False

    def test_check_proxy_reachable_is_true(self, mocker):
        """Достижимый прокси даёт True (config с host/port передаются)."""
        mocker.patch("socket.create_connection",
                     return_value=mocker.MagicMock())
        assert _check_proxy({"host": "192.168.1.107", "port": 1080}) is True
