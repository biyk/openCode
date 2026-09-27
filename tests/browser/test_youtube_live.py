"""Живые тесты YouTube на тестовом ролике в НОВОЙ вкладке.

Не трогают активную вкладку с боевым роликом: тестовое видео всегда
открывается в свежей вкладке и закрывается в конце. Перед тестами
дебаг-браузер (Brave, порт 9222) поднимается автоматически через
ensure_browser: без браузера live-тесты не проверяют ничего, поэтому
они не скипаются, а запускают браузер (падают, если он не стартовал).
Если же что-то УЖЕ играет (системное медиа или боевой ролик),
тест скипается: открытие ютуба и плей/пауза пропускаются, чтобы не
вмешиваться в воспроизведение и не ловить ложные падения.
YouTube доступен только через прокси: прокси-гейт проверяется раньше
всего — без прокси модуль скипается, не поднимая браузер.
"""
from __future__ import annotations

import platform
import subprocess
import time

import pytest

from lib.browser import cdp_client as cdc
from lib.browser import youtube_live as yl
from lib.browser_control import ensure_browser
from lib.voice_cmd.commands import CommandMatcher
from lib.voice_cmd.config_loader import get_device_commands_path
from lib.runtime.media import is_media_playing
from lib.runtime.status import StatusStore
from lib.runtime.status_checkers import _check_proxy

TEST_VIDEO_ID = "y65necIJU2Y"
TEST_VIDEO_URL = "https://www.youtube.com/watch?v=" + TEST_VIDEO_ID

# Ждём, пока OS-медиаклавиша дойдёт до плеера.
PAUSE_SETTLE_S = 2.0


def _proxy_ready() -> bool:
    """Проверяет прокси так же, как рантайм: статус proxy из status.json."""
    commands_file = get_device_commands_path(platform.node())
    store = StatusStore(StatusStore.path_for_commands_file(commands_file))
    if store.enabled:
        return store.refresh("proxy")
    # Конфига статусов нет — дефолтная проверка 192.168.1.107:1080.
    return bool(_check_proxy())


@pytest.fixture(scope="module", autouse=True)
def browser_ready():
    """Пропускает live-тесты без прокси; иначе поднимает браузер (CDP 9222).

    YouTube достигается только через прокси — без него тесты проверить
    ничего не могут, поэтому скип ставится до запуска браузера. Если
    браузер уже открыт — просто проверяется порт. Если закрыт —
    запускается (Brave, отдельный профиль) и ждётся готовность. Не
    удалось запустить → тест падает: skip без браузера бессмыслен.
    """
    if not _proxy_ready():
        pytest.skip("прокси недоступен — youtube live-тесты пропускаются")
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
        _close_stale_test_tabs()
        busy = _media_busy()
        if busy:
            pytest.skip(f"{busy} — пропускаем открытие ютуба и плей/паузу")
        tabs_before = {t.get("id") for t in cdc._list_tabs()}
        watch_before = _watch_tabs()

        tab = yl.youtube_open_test_video(TEST_VIDEO_URL)
        assert tab is not None, "не удалось открыть тестовый ролик"
        try:
            # 1. Открыт в НОВОЙ вкладке, а не в существующей.
            assert tab.get("id") not in tabs_before, (
                "ролик открылся в существующей вкладке, а не в новой")
            assert f"watch?v={TEST_VIDEO_ID}" in yl._tab_url(tab)

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
        # 5. Боевой ролик (существовавшие watch-вкладки) не тронут:
        # ни одна из них не закрылась и не уехала. Новые вкладки за
        # время прогона — не вина теста (юзер/автоплей), тестовая
        # проверялась выше на закрытие по id.
        assert not (watch_before - _watch_tabs()), (
            "существующие watch-вкладки изменились")


def _close_stale_test_tabs() -> None:
    """Закрывает вкладки тестового ролика, оставшиеся от упавших прогонов.

    Иначе осиротевшее тестовое видео играет → is_media_playing()
    истинна → тест вечно скипал бы сам себя.
    """
    for t in cdc._list_tabs():
        if TEST_VIDEO_ID in (t.get("url") or ""):
            cdc.close_tab(t)


def _media_busy() -> str:
    """Причина пропустить тест, если что-то уже играет (пусто — свободно)."""
    if is_media_playing():
        return "системное медиа проигрывается"
    for t in cdc._list_tabs():
        if t.get("type", "page") not in ("page", ""):
            continue
        url = t.get("url", "")
        if ("watch?v=" in url and TEST_VIDEO_ID not in url
                and yl._player_state(t) == "playing"):
            return "боевой ролик в браузере играет"
    return ""


def _watch_tabs() -> set:
    """id обычных вкладок с роликом (боевой ролик), кроме тестового."""
    result = set()
    for t in cdc._list_tabs():
        if t.get("type", "page") not in ("page", ""):
            continue
        url = t.get("url", "")
        if "watch?v=" in url and TEST_VIDEO_ID not in url:
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
