"""Живые тесты bin/get_volume.ps1: уровень и mute — независимые переключатели.

Проверяет, что `-Set X` сам по себе звук НЕ включает (только уровень) и что
`-Unmute` снимает mute, не трогая уровень — ровно та развязка, из-за которой
будильник проиграл «в заглушенный» endpoint: cron-скрипт ставил 40%, а флаг
mute оставался включённым. Тесты трогают реальный мастер-выход Windows и
возвращают его в исходное состояние.
"""
from __future__ import annotations

import platform
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VOLUME_PS1 = REPO_ROOT / "bin" / "get_volume.ps1"

BASELINE_VOLUME = 70.0
VOLUME_TOLERANCE = 1.0
SETTLE_S = 0.4


def _ps1_args(*args: str) -> list[str]:
    """Базовый вызов get_volume.ps1 (инвариантный вывод, без профиля)."""
    return [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(VOLUME_PS1), *args,
    ]


def _run(*args: str) -> str:
    res = subprocess.run(
        _ps1_args(*args), capture_output=True, text=True,
        timeout=60, cwd=str(REPO_ROOT),
    )
    if res.returncode != 0:
        raise AssertionError(
            f"get_volume.ps1 {' '.join(args)}: {res.stderr.strip()}")
    return res.stdout.strip()


def _get_volume() -> float:
    """Текущий уровень мастера (0..100)."""
    return float(_run())


def _get_mute() -> bool:
    """Текущий mute-флаг мастера (True = звук выключен)."""
    return _run("-ShowMute") == "mute=on"


def _set_volume(value: float) -> None:
    _run("-Set", f"{value:.1f}")
    time.sleep(SETTLE_S)


def _set_mute(muted: bool) -> None:
    _run("-Mute" if muted else "-Unmute")
    time.sleep(SETTLE_S)


@pytest.fixture
def restore_audio():
    """Восстанавливает и уровень, и mute мастера после каждого теста."""
    vol0 = _get_volume()
    mute0 = _get_mute()
    try:
        yield
    finally:
        if mute0:
            _set_mute(True)
        else:
            _set_mute(False)
        _set_volume(vol0)


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only")
class TestVolumeMuteDecoupling:
    """Уровень и mute — разные вещи: SetX не трогает mute, Unmute — уровень."""

    def test_show_mute_roundtrip(self, restore_audio):
        """-Mute/-Unmute переключают флаг, который читается через -ShowMute."""
        _set_mute(False)
        assert _get_mute() is False
        _set_mute(True)
        assert _get_mute() is True
        _set_mute(False)
        assert _get_mute() is False

    def test_set_does_not_touch_mute(self, restore_audio):
        """`-Set X` НЕ снимает mute: на мьют-флаге уровень меняется, а звук — нет.

        Некоторые драйверы Windows при `SetMasterVolumeLevelScalar` авто-снимают
        mute — на них тест скипается (критично лишь то, что `-Unmute` в
        будильнике гарантированно снимает mute; на « авто-анмьют»-драйверах это
        просто noop). См. README-примечание в шапке файла.
        """
        _set_mute(True)
        _set_volume(BASELINE_VOLUME)
        assert abs(_get_volume() - BASELINE_VOLUME) <= VOLUME_TOLERANCE, (
            "Set не поднял уровень")
        if _get_mute() is not True:
            pytest.skip(
                "драйвер эндпоинта авто-снимает mute на Set — "
                "проверка неприменима на этом железе")
        # Если дошли сюда — mute держится, а значит путь «Set сам по себе глушит»
        # реален, и явный -Unmute в будильнике обязателен.
        out = _run("-Set", f"{BASELINE_VOLUME:.1f}", "-Unmute")
        time.sleep(SETTLE_S)
        assert _get_mute() is False, (
            "Set+Unmute обязан снять mute (проверка пары к предыдущему assert)")
        assert abs(float(out) - BASELINE_VOLUME) <= VOLUME_TOLERANCE, (
            "Set+Unmute должен вернуть тот же уровень")

    def test_unmute_does_not_touch_level(self, restore_audio):
        """`-Unmute` снимает mute, уровень остаётся прежним."""
        _set_volume(BASELINE_VOLUME)
        _set_mute(True)
        before = _get_volume()
        _set_mute(False)
        assert _get_mute() is False
        assert abs(_get_volume() - before) <= VOLUME_TOLERANCE, (
            "Unmute не должен двигать громкость")

    def test_set_and_unmute_together(self, restore_audio):
        """`-Set 40 -Unmute` (шаг будильника):mute снят, уровень 40."""
        _set_mute(True)
        _set_volume(BASELINE_VOLUME)
        out = _run("-Set", "40", "-Unmute")
        time.sleep(SETTLE_S)
        assert _get_mute() is False, "Set+Unmute обязан снять mute"
        assert abs(float(out) - 40.0) <= VOLUME_TOLERANCE, (
            f"Set+Unmute должен вернуть новый уровень: {out}")

    def test_mute_and_unmute_conflict_rejected(self, restore_audio):
        """Одновременно -Mute и -Unmute — ошибка (exit != 0)."""
        res = subprocess.run(
            _ps1_args("-Mute", "-Unmute"), capture_output=True, text=True,
            timeout=60, cwd=str(REPO_ROOT),
        )
        assert res.returncode != 0, (
            "-Mute -Unmute вместе не должны молча проходить")
