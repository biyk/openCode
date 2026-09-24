"""Живые тесты YouTube на тестовом ролике в НОВОЙ вкладке.

Не трогают активную вкладку с боевым роликом: тестовое видео всегда
открывается в свежей вкладке и закрывается в конце. Перед тестами
дебаг-браузер (Brave, порт 9222) поднимается автоматически через
ensure_browser: без браузера live-тесты не проверяют ничего, поэтому
они не скипаются, а запускают браузер (падают, если он не стартовал).
"""
from __future__ import annotations

import platform
import subprocess
import time

import pytest

from lib import cdp_client as cdc
from lib import youtube_live as yl
from lib.browser_control import ensure_browser
from lib.commands import CommandMatcher
from lib.config_loader import get_device_commands_path

TEST_VIDEO_URL = "https://www.youtube.com/watch?v=y65necIJU2Y"

# Ждём, пока OS-медиаклавиша дойдёт до плеера.
PAUSE_SETTLE_S = 2.0


@pytest.fixture(scope="module", autouse=True)
def browser_ready():
    """Поднимает дебаг-браузер (CDP 9222) перед live-тестами YouTube.

    Если браузер уже открыт — просто проверяет порт. Если закрыт —
    запускает (Brave, отдельный профиль) и ждёт готовности. Не удалось
    запустить → тест падает: skip без браузера бессмыслен.
    """
    if not ensure_browser():
        pytest.fail(
            "дебаг-браузер (Brave, порт 9222) не запустился — "
            "live-тесты YouTube невозможны")


@pytest.fixture
def matcher() -> CommandMatcher:
    """Матчер с реальным commands.json текущего устройства."""
    return CommandMatcher(get_device_commands_path(platform.node()))


class TestYoutubeLiveCombined:
    """Комбинированный сценарий: открыть ролик → пауза → закрыть."""

    def test_open_play_pause_close(self, matcher, live_announce):
        """Тестовый ролик играет в новой вкладке, пауза срабатывает,
        вкладка закрывается, боевой ролик не тронут."""
        tabs_before = {t.get("id") for t in cdc._list_tabs()}
        watch_before = _watch_tabs()

        tab = yl.youtube_open_test_video(TEST_VIDEO_URL)
        assert tab is not None, "не удалось открыть тестовый ролик"
        try:
            # 1. Открыт в НОВОЙ вкладке, а не в существующей.
            assert tab.get("id") not in tabs_before, (
                "ролик открылся в существующей вкладке, а не в новой")
            assert "watch?v=y65necIJU2Y" in yl._tab_url(tab)

            # 2. Видео реально играет.
            assert _wait_state(tab, "playing"), (
                "тестовый ролик не начал играть")

            # 3. Команда «пауза» (OS-медиаклавиша) ставит на паузу.
            cmd = matcher.get_command("playpause")
            assert cmd, "playpause: пустая shell-команда"
            subprocess.run(cmd, shell=True, timeout=30)
            assert _wait_state(tab, "paused"), (
                "после playpause видео не на паузе")
        finally:
            # 4. Закрываем тестовую вкладку.
            cdc.close_tab(tab)

        time.sleep(1)
        tabs_after = {t.get("id") for t in cdc._list_tabs()}
        assert tab.get("id") not in tabs_after, "тестовая вкладка не закрыта"
        # 5. Боевой ролик (существовавшие watch-вкладки) не тронут.
        assert _watch_tabs() == watch_before, (
            "существующие watch-вкладки изменились")


def _watch_tabs() -> set:
    """id обычных вкладок с роликом (боевой ролик), кроме тестового."""
    result = set()
    for t in cdc._list_tabs():
        if t.get("type", "page") not in ("page", ""):
            continue
        url = t.get("url", "")
        if "watch?v=" in url and "y65necIJU2Y" not in url:
            result.add(t.get("id"))
    return result


def _wait_state(tab: dict, expected: str, timeout: float = 20.0) -> bool:
    """Ждёт, пока состояние плеера станет expected."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if yl._player_state(tab) == expected:
            time.sleep(PAUSE_SETTLE_S)
            return yl._player_state(tab) == expected
        time.sleep(0.5)
    return False
