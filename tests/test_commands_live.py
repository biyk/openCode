"""Живые функциональные тесты команд: реальное выполнение на хосте.

Проверяет, что команды из commands.json действительно работают
(громче/тише реально меняют системную громкость), а не только
матчатся. Состояние системы восстанавливается после каждого теста.
"""
from __future__ import annotations

import platform
import subprocess
import time
from pathlib import Path

import pytest

from lib.commands import CommandMatcher
from lib.config_loader import get_device_commands_path

REPO_ROOT = Path(__file__).resolve().parents[1]
VOLUME_PS1 = REPO_ROOT / "bin" / "get_volume.ps1"

# Уровень, с которого стартует проверка (не упираемся в 0/100%).
BASELINE_VOLUME = 70.0
# Минимальное реальное изменение, считающееся успехом (%).
VOLUME_TOLERANCE = 1.0
# Даём Windows-медиаклавишам доехать до аудио-движка.
VOLUME_SETTLE_S = 0.4


def _run_shell(cmd: str) -> subprocess.CompletedProcess:
    """Выполняет shell-команду из commands.json с cwd = репозиторий."""
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        timeout=60, cwd=str(REPO_ROOT),
    )


def _ps1_args(*args: str) -> list[str]:
    """Базовый вызов get_volume.ps1 (инвариантный вывод, без профиля)."""
    return [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(VOLUME_PS1), *args,
    ]


def _get_volume() -> float:
    """Текущий уровень громкости в % (0..100)."""
    res = subprocess.run(
        _ps1_args(), capture_output=True, text=True,
        timeout=60, cwd=str(REPO_ROOT),
    )
    if res.returncode != 0:
        raise AssertionError(f"get_volume.ps1 failed: {res.stderr.strip()}")
    return float(res.stdout.strip())


def _set_volume(value: float) -> None:
    """Устанавливает уровень громкости в % (точный restore)."""
    res = subprocess.run(
        _ps1_args("-Set", f"{value:.1f}"),
        capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT),
    )
    if res.returncode != 0:
        raise AssertionError(f"get_volume.ps1 -Set failed: {res.stderr.strip()}")
    time.sleep(VOLUME_SETTLE_S)


@pytest.fixture
def matcher() -> CommandMatcher:
    """Матчер с реальным commands.json текущего устройства."""
    path = get_device_commands_path(platform.node())
    return CommandMatcher(path)


def test_sleepmode_phrase_matches_command(matcher):
    """«спать»/«я спать»/«я пошел спать» (и варианты) матчатся на sleepmode."""
    for window in (["алиса спать"], ["алиса я спать"], ["алиса иду спать"],
                   ["алиса я лег спать"], ["лег спать пожалуйста"],
                   ["алиса я лёг спать"], ["алиса я пошел спать"],
                   ["алиса я пошёл спать"]):
        cmd_id, _settings, wait = matcher.find_command(window)
        assert cmd_id == "sleepmode", f"{window}: ожидался sleepmode, получил {cmd_id}"
        assert not wait


def test_sleepmode_sequence_steps_resolvable(matcher):
    """Sequence sleepmode собирается из шагов sleepvolume + sleepfix."""
    steps = matcher.sequences()["sleepmode"]["steps"]
    assert steps == ["sleepvolume", "sleepfix"]
    assert "get_volume.ps1" in (matcher.get_command("sleepvolume") or "")
    assert "lib.sleep_event" in (matcher.get_command("sleepfix") or "")


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only test")
class TestVolumeCommandsLive:
    """volumeup/volumedown: реальный запуск + измерение системной громкости."""

    @pytest.fixture(autouse=True)
    def _announce(self, live_announce):
        """Перед live-тестами озвучиваем «Внимание, идёт тестирование»."""

    def test_volumeup_increases_real_volume(self, matcher):
        """Команда «громче» реально поднимает уровень звука."""
        original = _get_volume()
        _set_volume(BASELINE_VOLUME)
        try:
            cmd = matcher.get_command("volumeup")
            assert cmd, "volumeup: пустая shell-команда"
            result = _run_shell(cmd)
            assert result.returncode == 0, (
                f"volumeup завершился с кодом {result.returncode}: "
                f"{result.stderr.strip()}"
            )
            time.sleep(VOLUME_SETTLE_S)
            after = _get_volume()
            assert after >= BASELINE_VOLUME + VOLUME_TOLERANCE, (
                f"громкость не выросла: было {BASELINE_VOLUME}, стало {after}"
            )
        finally:
            _set_volume(original)

    def test_volumedown_decreases_real_volume(self, matcher):
        """Команда «тише» реально опускает уровень звука."""
        original = _get_volume()
        _set_volume(BASELINE_VOLUME)
        try:
            cmd = matcher.get_command("volumedown")
            assert cmd, "volumedown: пустая shell-команда"
            result = _run_shell(cmd)
            assert result.returncode == 0, (
                f"volumedown завершился с кодом {result.returncode}: "
                f"{result.stderr.strip()}"
            )
            time.sleep(VOLUME_SETTLE_S)
            after = _get_volume()
            assert after <= BASELINE_VOLUME - VOLUME_TOLERANCE, (
                f"громкость не уменьшилась: было {BASELINE_VOLUME}, стало {after}"
            )
        finally:
            _set_volume(original)

    def test_sleepvolume_sets_volume_to_one(self, matcher):
        """Шаг sleepvolume опускает громкость ровно до 1%."""
        original = _get_volume()
        _set_volume(BASELINE_VOLUME)
        try:
            cmd = matcher.get_command("sleepvolume")
            assert cmd, "sleepvolume: пустая shell-команда"
            result = _run_shell(cmd)
            assert result.returncode == 0, (
                f"sleepvolume завершился с кодом {result.returncode}: "
                f"{result.stderr.strip()}"
            )
            time.sleep(VOLUME_SETTLE_S)
            assert abs(_get_volume() - 1.0) <= VOLUME_TOLERANCE, (
                "sleepvolume: громкость не опустилась до 1%"
            )
        finally:
            _set_volume(original)

    def test_volume_restored_after_tests(self, matcher):
        """После тестов громкость возвращается к исходному уровню."""
        original = _get_volume()
        _set_volume(BASELINE_VOLUME)
        try:
            _run_shell(matcher.get_command("volumeup"))
            time.sleep(VOLUME_SETTLE_S)
        finally:
            _set_volume(original)
        assert abs(_get_volume() - original) <= VOLUME_TOLERANCE, (
            f"громкость не восстановлена: должно быть {original}"
        )
