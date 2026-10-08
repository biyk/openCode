"""Живой регресс утреннего будильника: вкладка с роликом — ровно одна.

Проверяет шаг 2 `cron/jobs/wake_video_and_volume.ps1` на идемпотентность:
если вкладка с этим видео id уже открыта, скрипт НЕ плодит вторую. Двойная
вкладка — фактический баг, который пользователь словил после ручных правок
crontab.json: соседние минуты (или рестарт процесса) приводили к двум
`open-new` подряд.

Зависит от живого CDP-браузера на :9222 (как tests/browser/test_youtube_live)
— при недоступности скипается, чтобы не ронять общий прогон.
"""
from __future__ import annotations

import platform
import re
import subprocess
import time
from pathlib import Path

import pytest

from lib.browser.cdp_client import close_tab, _list_tabs

REPO_ROOT = Path(__file__).resolve().parents[2]
WAKE_PS1 = REPO_ROOT / "cron" / "jobs" / "wake_video_and_volume.ps1"

# Видео-id, вшитый в скрипт, — здесь ради поиска вкладки среди tabs.
VIDEO_ID_RE = re.compile(r'\$video\s*=\s*"([^"]+)"')


def _video_id() -> str:
    """Достаёт id ролика из wake_video_and_volume.ps1 (не дублировать литерал)."""
    text = WAKE_PS1.read_text(encoding="utf-8-sig")
    match = VIDEO_ID_RE.search(text)
    assert match, "в скрипте будильника не найден $video"
    return match.group(1)


def _run_wake() -> str:
    res = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(WAKE_PS1)],
        capture_output=True, text=True, timeout=180,
        cwd=str(REPO_ROOT),
    )
    if res.returncode != 0:
        raise AssertionError(
            f"wake_video_and_volume.ps1 упал: rc={res.returncode}\n"
            f"stdout:\n{res.stdout}\nstderr:\n{res.stderr}")
    return res.stdout


def _video_tab_count(video: str) -> int:
    return sum(1 for t in _list_tabs()
               if video in (t.get("url") or "")
               and t.get("type", "page") in ("page", ""))


def _close_video_tabs(video: str) -> None:
    for tab in list(_list_tabs()):
        if video in (tab.get("url") or ""):
            close_tab(tab)


@pytest.fixture(scope="module")
def browser_up():
    """Шлюз живого теста: CDP-браузер на :9222 должен отвечать."""
    res = subprocess.run(
        ["python", "-m", "lib.browser_control", "status"],
        capture_output=True, text=True, timeout=15,
        cwd=str(REPO_ROOT),
    )
    if res.returncode != 0:
        pytest.skip("CDP-браузер на :9222 не отвечает — тест живой")


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only")
class TestWakeScriptTabIdempotent:
    """Шаг 2 будильника: вторая вкладка с тем же роликом не появляется."""

    def test_two_runs_one_tab(self, browser_up):
        video = _video_id()
        _close_video_tabs(video)
        time.sleep(0.5)
        assert _video_tab_count(video) == 0, "до теста уже есть вкладка"

        _run_wake()
        after_first = _video_tab_count(video)
        assert after_first == 1, (
            f"первый прогон обязан открыть 1 вкладку, "
            f"факт {after_first}")

        _run_wake()
        after_second = _video_tab_count(video)
        assert after_second == 1, (
            f"второй прогон НЕ должен плодить вкладку "
            f"(идемпотентность шага 2): ждали 1, получили {after_second}")

        _close_video_tabs(video)
