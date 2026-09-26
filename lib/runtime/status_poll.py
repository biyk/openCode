"""Фоновый опрос статусов (миксин хранилища)."""

import os
import sys
import threading
import time


class StatusPollMixin:
    """Миксин StatusStore: daemon-поток опроса и заголовок консоли."""

    def _update_title(self) -> None:
        """Обновляет заголовок окна консоли текущими статусами (Windows)."""
        if sys.platform != "win32":
            return
        try:
            parts = [f"{n}={'on' if v else 'off'}"
                     for n, v in sorted(self.snapshot().items())]
            os.system(f"title Voice: {' '.join(parts)}")
        except Exception:
            pass

    def start(self) -> None:
        """Запускает фоновый опрос статусов (daemon-поток)."""
        if not self.enabled or self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="status-poll")
        self._thread.start()

    def stop(self) -> None:
        """Останавливает фоновый опрос."""
        self._stop_event.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    def _loop(self) -> None:
        """Цикл опроса: проверяет просроченные статусы раз в секунду."""
        while not self._stop_event.is_set():
            cycle_start = time.monotonic()
            try:
                self.reload()
                now = time.monotonic()
                for name in list(self._defs):
                    last = self._last_check.get(name, 0.0)
                    if now - last >= self._interval_for(name):
                        self.refresh(name)
            except Exception:
                pass
            elapsed = time.monotonic() - cycle_start
            self._stop_event.wait(max(0.0, 1.0 - elapsed))
