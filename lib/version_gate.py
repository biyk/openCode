"""Проверка версий приложения и проекта."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

from lib.version import get_version


PROJECT_VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"


def read_project_version() -> str:
    try:
        return PROJECT_VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return "0.0.0"


def check_versions_or_exit(app_version: str, project_version: str) -> None:
    if not project_version or project_version == "0.0.0":
        return
    if app_version != project_version:
        print(
            f"[Version] Несовпадение: приложение={app_version}, проект={project_version}. "
            "Приложение выключается."
        )
        sys.exit(1)


@dataclass(frozen=True)
class VersionSnapshot:
    app_version: str
    project_version: str


def snapshot() -> VersionSnapshot:
    return VersionSnapshot(
        app_version=get_version(),
        project_version=read_project_version(),
    )
