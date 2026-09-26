"""Тесты хранилища статусов: фоновый опрос."""


import json
import tempfile
import os
import sys
from lib.runtime.status import StatusStore


def _write_status_file(defs):
    """Создаёт временный status.json, возвращает путь."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"statuses": defs}, f)
    return path


class TestStatusStoreThread:
    """Запуск и остановка daemon-потока."""

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
