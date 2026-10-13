#!/usr/bin/env python3
"""Периодическая проверка версий приложения и проекта."""

import threading

from lib.versioning.version_gate import snapshot
from lib.versioning.version_gate import check_versions_or_exit
from lib.monitor import registry
import os


def start_version_checker(stop_event: threading.Event, interval_s: float = 120.0) -> None:
    def _run() -> None:
        while not stop_event.is_set():
            registry.report("version", "Проверка версий", registry.WORKING)
            snap = snapshot()
            if snap.app_version != snap.project_version and snap.project_version != "0.0.0":
                print(
                    "[Version] Несовпадение: "
                    f"приложение={snap.app_version}, проект={snap.project_version}. "
                    "Приложение выключается."
                )
                os._exit(1)
            check_versions_or_exit(snap.app_version, snap.project_version)
            registry.report("version", "Проверка версий", registry.IDLE,
                            f"цикл {interval_s:.0f}с")
            stop_event.wait(interval_s)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
