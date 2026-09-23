"""Хранилище статусов системы с фоновым опросом.

Статусы (vpn, media, browser_youtube, ...) описываются в отдельном
targets/<host>/status.json:

{
  "statuses": {
    "vpn": {
      "description": "VPN включён (youtube доступен)",
      "checker": "vpn",
      "interval": 5,
      "need_message": "Включи VPN вручную"
    },
    "custom": {
      "check": "curl -s -o NUL https://example.com",
      "interval": 10
    }
  }
}

Проверка статуса — либо встроенный checker ("checker": <имя>),
либо shell-команда ("check": <строка или per-OS dict>, exit 0 = активен).
StatusStore опрашивает все статусы в фоне (daemon-поток) и хранит
последние значения потокобезопасно. Команды в commands.json ссылаются
на статусы через поле "requires".
"""

import json
import os
import platform
import subprocess
import threading
import time
from typing import Any, Callable, Optional


from lib.status_checkers import (
    _check_browser,
    _check_browser_youtube,
    _check_media,
    _check_media_session,
    _check_vpn,
)
from lib.status_poll import StatusPollMixin


BUILTIN_CHECKERS: dict[str, Callable[[], bool]] = {
    "vpn": _check_vpn,
    "media": _check_media,
    "media_session": _check_media_session,
    "browser": _check_browser,
    "browser_youtube": _check_browser_youtube,
}


class StatusStore(StatusPollMixin):
    """Потокобезопасное хранилище статусов с фоновым опросом."""

    def __init__(self, status_file: Optional[str] = None,
                 default_interval: float = 5.0, output: Any = None) -> None:
        self._status_file = status_file
        self._default_interval = default_interval
        self._output = output
        self._defs: dict[str, dict] = {}
        self._states: dict[str, bool] = {}
        self._last_check: dict[str, float] = {}
        self._mtime = 0.0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._load()

    @staticmethod
    def path_for_commands_file(commands_file: str) -> str:
        """Возвращает путь к status.json рядом с commands.json."""
        return os.path.join(os.path.dirname(commands_file), "status.json")

    @property
    def enabled(self) -> bool:
        """Активно ли хранилище (есть ли описания статусов)."""
        return bool(self._defs)

    def _load(self) -> None:
        """Читает описания статусов из файла."""
        self._defs = {}
        if not self._status_file:
            return
        try:
            with open(self._status_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._defs = data.get("statuses", {})
            self._mtime = os.path.getmtime(self._status_file)
        except Exception:
            self._defs = {}
        with self._lock:
            for name in self._defs:
                self._states.setdefault(name, False)
                self._last_check.setdefault(name, 0.0)

    def reload(self) -> None:
        """Перечитывает файл статусов, если он изменился."""
        if not self._status_file:
            return
        try:
            mtime = os.path.getmtime(self._status_file)
        except OSError:
            return
        if mtime == self._mtime:
            return
        self._load()

    def _interval_for(self, name: str) -> float:
        """Интервал опроса статуса в секундах."""
        try:
            return float(self._defs.get(name, {}).get(
                "interval", self._default_interval))
        except (TypeError, ValueError):
            return self._default_interval

    def _resolve_shell(self, spec: Any) -> Optional[str]:
        """Возвращает shell-команду проверки с учётом платформы."""
        if isinstance(spec, dict):
            system = platform.system().lower()
            return spec.get(system) or spec.get("default")
        return spec

    def _run_check(self, name: str) -> bool:
        """Выполняет одну проверку статуса, True = активен."""
        spec = self._defs.get(name, {})
        try:
            if "checker" in spec:
                checker = BUILTIN_CHECKERS.get(spec["checker"])
                if checker is None:
                    return False
                return bool(checker())
            if "check" in spec:
                cmd = self._resolve_shell(spec["check"])
                if not cmd:
                    return False
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, timeout=10)
                return result.returncode == 0
        except Exception:
            return False
        return False

    def refresh(self, name: str) -> bool:
        """Проверяет статус прямо сейчас, сохраняет и возвращает значение."""
        value = self._run_check(name)
        with self._lock:
            old = self._states.get(name, False)
            self._states[name] = value
            self._last_check[name] = time.monotonic()
        if value != old:
            self._update_title()
            if self._output is not None:
                state = "on" if value else "off"
                self._output.print_info(f"[Status] {name}: {state}")
        return value

    def refresh_all(self) -> dict[str, bool]:
        """Проверяет все статусы прямо сейчас."""
        return {name: self.refresh(name) for name in list(self._defs)}

    def is_active(self, name: str) -> bool:
        """Возвращает кэшированное значение статуса (неизвестный = False)."""
        with self._lock:
            return self._states.get(name, False)

    def snapshot(self) -> dict[str, bool]:
        """Возвращает копию всех текущих значений."""
        with self._lock:
            return dict(self._states)

    def ensure(self, names: list[str]) -> list[str]:
        """Имена неактивных статусов (выключенные перепроверяются разово)."""
        if not self.enabled:
            return []
        missing = [n for n in names if not self.is_active(n)]
        still_missing = []
        for name in missing:
            if not self.refresh(name):
                still_missing.append(name)
        return still_missing

    def set(self, name: str, value: bool) -> None:
        """Оптимистично выставляет статус (после успешного шага команды)."""
        with self._lock:
            if name in self._defs:
                self._states[name] = value

    def need_message(self, name: str) -> str:
        """Человекочитаемое сообщение, что делать при отсутствии статуса."""
        spec = self._defs.get(name, {})
        message = spec.get("need_message")
        if message:
            return str(message)
        return f"Нужен статус: {name}"
