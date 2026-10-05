"""Тесты диагностики Bluetooth (lib.runtime.bluetooth).

Разбор заряда и отчёта — на фиктивных данных, без Windows и без радио. Живой
прогон (настоящий PowerShell + радио) выключен по умолчанию: VOICE_LIVE_BT=1.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from lib.runtime import bluetooth


def _dev(name="H30i", pct=None, charging=False, source="none",
         conn_count=0, profiles=(), connected=None):
    """Карточка устройства в формате bin/bt_devices.ps1."""
    if connected is None:
        connected = bool(conn_count)
    return {
        "name": name, "mac": "18:9C:2C:1C:6F:E5", "transport": "BREDR",
        "present": True, "status": "OK", "connected": connected,
        "conn_count": conn_count, "profiles": list(profiles),
        "instance": r"BTHENUM\DEV_189C2C1C6FE5\7&BD0FD55&0&X",
        "battery": {"percent": pct, "charging": charging, "source": source},
    }


def _data(*devs):
    return {"os_build": "22000", "battery_total": 1,
            "radios": [{"name": "Realtek Bluetooth Adapter", "status": "OK"}],
            "devices": list(devs)}


@pytest.fixture
def win(monkeypatch, tmp_path):
    """Мир «это Windows, скрипт на месте»; остаётся подменить вывод PS."""
    script = tmp_path / "bt.ps1"
    script.write_text("# x", encoding="utf-8")
    monkeypatch.setattr(bluetooth.os, "name", "nt")
    monkeypatch.setattr(bluetooth, "SCRIPT", script)

    def fake(stdout="", stderr="", rc=0, exc=None):
        def run(*a, **kw):
            if exc is not None:
                raise exc
            return subprocess.CompletedProcess(
                a, rc, stdout=stdout, stderr=stderr)
        monkeypatch.setattr(bluetooth.subprocess, "run", run)
    return fake


class TestBatteryText:
    """Строка про заряд: измеренный процент либо «неизвестно» с причиной."""

    @pytest.mark.parametrize("pct, charging, source, frags", [
        (42, False, "none", ["42%", "не на зарядке"]),
        (5, True, "battery-devnode", ["5%", "на зарядке", "контейнера"]),
        # 0% — измеренное значение, а не отсутствие данных
        (0, False, "none", ["0%"]),
    ])
    def test_measured_percent(self, pct, charging, source, frags):
        text = bluetooth.battery_text(
            _dev(pct=pct, charging=charging, source=source))
        for frag in frags:
            assert frag in text

    @pytest.mark.parametrize("source, extra", [
        ("none", "нет источника заряда"),
        ("gatt-service-visible", "GATT"),
        ("something-new", ""),        # новый код не роняет отчёт
    ])
    def test_no_percent_says_unknown(self, source, extra):
        text = bluetooth.battery_text(_dev(pct=None, source=source))
        assert "неизвестно" in text and extra in text

    def test_missing_battery_key(self):
        assert "неизвестно" in bluetooth.battery_text({"name": "x"})


class TestDevices:
    """devices() не падает на неожиданной форме ответа."""

    def test_plain_list(self):
        assert bluetooth.devices(_data(_dev())) == [_dev()]

    @pytest.mark.parametrize("data", [{"radios": []}, {"devices": {"a": 1}}])
    def test_missing_or_bad_shape(self, data):
        assert bluetooth.devices(data) == []


class TestFormatReport:
    """Отчёт: список, режим «только заряд», сообщение об отказе."""

    def test_error_is_one_line(self):
        out = bluetooth.format_report({"error": "не Windows"})
        assert out == "Bluetooth недоступен: не Windows"

    def test_no_devices(self):
        out = bluetooth.format_report(_data())
        assert "Bluetooth-устройств: 0" in out
        assert "ни одного спаренного устройства" in out

    def test_lists_profiles_and_connection(self):
        dev = _dev(profiles=("HFP", "A2DP"), conn_count=1)
        out = bluetooth.format_report(_data(dev))
        assert "HFP, A2DP" in out and "подключено" in out
        assert "радио: Realtek Bluetooth Adapter" in out

    def test_le_without_conn_count_says_unknown(self):
        dev = _dev(name="H30i_LE", conn_count=None, connected=False)
        assert "отключено (не известно)" in bluetooth.format_report(_data(dev))

    def test_only_battery_keeps_measured_only(self):
        known = _dev(name="Mouse", pct=77, source="battery-devnode")
        out = bluetooth.format_report(
            _data(_dev(name="H30i"), known), only_battery=True)
        assert "Mouse" in out and "77%" in out

    def test_only_battery_without_measurements_says_so(self):
        out = bluetooth.format_report(
            _data(_dev(pct=None)), only_battery=True)
        assert "процент не известен ни у одного устройства" in out
        # устройства всё равно показаны — иначе непонятно, про что вывод
        assert "H30i" in out


class TestCollectFailOpen:
    """collect() никогда не бросает: любой сбой — словарь с ключом error."""

    def test_not_windows(self, monkeypatch):
        monkeypatch.setattr(bluetooth.os, "name", "posix")
        assert bluetooth.collect() == {"error": "не Windows"}

    def test_missing_script(self, monkeypatch, tmp_path):
        monkeypatch.setattr(bluetooth.os, "name", "nt")
        monkeypatch.setattr(bluetooth, "SCRIPT", tmp_path / "nope.ps1")
        assert "нет скрипта" in bluetooth.collect()["error"]

    def test_powershell_oserror(self, win):
        win(exc=OSError("no powershell"))
        assert "powershell" in bluetooth.collect()["error"]

    def test_timeout(self, win):
        win(exc=subprocess.TimeoutExpired("powershell", 1))
        assert "powershell" in bluetooth.collect()["error"]

    def test_empty_stdout_uses_stderr(self, win):
        win(stdout="", stderr="radio off", rc=1)
        assert bluetooth.collect() == {"error": "radio off"}

    def test_empty_everything(self, win):
        win(stdout="", stderr="", rc=1)
        assert bluetooth.collect() == {"error": "пустой вывод"}

    def test_broken_json(self, win):
        win(stdout="не json")
        assert "битый JSON" in bluetooth.collect()["error"]

    def test_json_that_is_not_an_object(self, win):
        win(stdout="[1, 2]")
        assert "не объект" in bluetooth.collect()["error"]

    def test_good_json_is_returned(self, win):
        win(stdout='{"devices": [], "radios": []}')
        assert bluetooth.collect() == {"devices": [], "radios": []}


def test_script_next_to_module_exists():
    """Без bin/bt_devices.ps1 фича мертва — путь обязан существовать."""
    assert isinstance(bluetooth.SCRIPT, Path)
    assert bluetooth.SCRIPT.exists(), bluetooth.SCRIPT


def test_main_prints_report_without_raising(monkeypatch, capsys):
    """CLI не падает, даже если собрать ничего не удалось."""
    monkeypatch.setattr(bluetooth, "collect", lambda **kw: {"error": "нет радио"})
    assert bluetooth.main([]) == 0
    assert "Bluetooth недоступен" in capsys.readouterr().out


@pytest.mark.skipif(
    os.environ.get("VOICE_LIVE_BT") != "1",
    reason="живой Bluetooth: включи VOICE_LIVE_BT=1",
)
def test_collect_live():
    """Реальный PowerShell: проверяем структуру ответа, а не состав устройств."""
    data = bluetooth.collect(timeout_s=180)
    assert "error" not in data, data["error"]
    assert isinstance(data.get("radios"), list)
    for dev in bluetooth.devices(data):
        assert dev["mac"] and "battery" in dev
