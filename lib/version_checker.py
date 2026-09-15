#!/usr/bin/env python3
"""Периодическая проверка версий приложения и проекта."""

import threading

from lib.version_gate import snapshot
from lib.version_gate import check_versions_or_exit


def start_version_checker(stop_event: threading.Event, interval_s: float = 120.0) -> None:
    def _run() -> None:
        while not stop_event.is_set():
            snap = snapshot()
            check_versions_or_exit(snap.app_version, snap.project_version)
            stop_event.wait(interval_s)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
