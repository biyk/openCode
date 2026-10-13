"""Тесты сборки монитора (`lib/monitor/launch.py`).

Никаких живых процессов: поднятие доски и смотритель OmniRouter подменяются —
иначе тестовый прогон гонял бы `omniroute restart` по настоящему.
"""
import os
import time

from lib.monitor import heartbeat, launch
from lib.monitor.registry import ServiceRegistry, WORKING
from lib.monitor.ui import TAB_ID
from lib.voice_cmd import knowledge_review


class _Matcher:
    def __init__(self, cfg):
        self._cfg = cfg

    def get_monitor_config(self):
        return self._cfg


class _BoomMatcher:
    def get_monitor_config(self):
        raise RuntimeError("нет секции monitor")


class _Out:
    def __init__(self):
        self.info = []
        self.errors = []

    def print_info(self, message):
        self.info.append(message)

    def print_error(self, message):
        self.errors.append(message)


def _no_watchdog(config, registry):
    return None


def test_start_monitor_disabled_returns_none():
    got = launch.start_monitor(_Matcher({"enabled": False}), output=_Out(),
                               registry=ServiceRegistry())
    assert got is None


def test_start_monitor_writes_heartbeat(tmp_path, monkeypatch):
    hb = str(tmp_path / "hb.json")
    monkeypatch.setattr(heartbeat, "default_path", lambda: hb)
    monkeypatch.setattr(launch, "build_watchdog", _no_watchdog)
    reg = ServiceRegistry()
    reg.report("stt", "Слушалка", WORKING)
    monitor = launch.start_monitor(
        _Matcher({"enabled": True, "auto_open": False}), output=_Out(),
        registry=reg)
    deadline = time.time() + 2
    while time.time() < deadline and not os.path.exists(hb):
        time.sleep(0.05)
    monitor.stop()
    assert os.path.exists(hb)


def test_broken_matcher_defaults_on_and_opens_board(tmp_path, monkeypatch):
    """Нет секции/нет конфига → живём по дефолтам: heartbeat + вкладка доски."""
    hb = str(tmp_path / "hb.json")
    monkeypatch.setattr(heartbeat, "default_path", lambda: hb)
    monkeypatch.setattr(launch, "build_watchdog", _no_watchdog)
    calls = []
    monkeypatch.setattr(knowledge_review, "launch",
                        lambda port=None, fragment="": calls.append(
                            (port, fragment)) or 0)
    monitor = launch.start_monitor(_BoomMatcher(), output=_Out(),
                                   registry=ServiceRegistry())
    assert monitor is not None
    assert calls == [(None, TAB_ID)]           # открыли сразу «Сервисы»
    monitor.stop()


def test_board_port_comes_from_config(tmp_path, monkeypatch):
    hb = str(tmp_path / "hb.json")
    monkeypatch.setattr(heartbeat, "default_path", lambda: hb)
    monkeypatch.setattr(launch, "build_watchdog", _no_watchdog)
    calls = []
    monkeypatch.setattr(knowledge_review, "launch",
                        lambda port=None, fragment="": calls.append(
                            (port, fragment)) or 0)
    monitor = launch.start_monitor(
        _Matcher({"enabled": True, "board_port": 8899}), output=_Out(),
        registry=ServiceRegistry())
    assert calls == [(8899, TAB_ID)]
    monitor.stop()


def test_board_failure_is_reported_not_raised(monkeypatch):
    out = _Out()

    def _down(port=None, fragment=""):
        return 1

    monkeypatch.setattr(knowledge_review, "launch", _down)
    launch.open_board(out, 8765)
    assert out.errors and "Доска не поднялась" in out.errors[0]


def test_open_board_swallows_exceptions(monkeypatch):
    out = _Out()

    def _boom(port=None, fragment=""):
        raise OSError("браузер лежит")

    monkeypatch.setattr(knowledge_review, "launch", _boom)
    launch.open_board(out, None)               # не должно бросить
    assert out.errors and "не открылась" in out.errors[0]


def test_auto_open_false_does_not_touch_browser(tmp_path, monkeypatch):
    hb = str(tmp_path / "hb.json")
    monkeypatch.setattr(heartbeat, "default_path", lambda: hb)
    monkeypatch.setattr(launch, "build_watchdog", _no_watchdog)

    def _never(port=None, fragment=""):
        raise AssertionError("доску открывать не должны")

    monkeypatch.setattr(knowledge_review, "launch", _never)
    monitor = launch.start_monitor(
        _Matcher({"enabled": True, "auto_open": False}), output=_Out(),
        registry=ServiceRegistry())
    assert monitor is not None and monitor.watchdog is None
    monitor.stop()


def test_watchdog_is_started_and_stopped_with_monitor(tmp_path, monkeypatch):
    hb = str(tmp_path / "hb.json")
    monkeypatch.setattr(heartbeat, "default_path", lambda: hb)
    monkeypatch.setattr(launch, "open_board", lambda output, port=None: None)
    started = {"n": 0, "stopped": 0}

    class _FakeWd:
        def start(self):
            started["n"] += 1

        def stop(self):
            started["stopped"] += 1

    monkeypatch.setattr(launch, "build_watchdog",
                        lambda config, registry: _FakeWd())
    monitor = launch.start_monitor(_Matcher({"enabled": True}), output=_Out(),
                                   registry=ServiceRegistry())
    assert started == {"n": 1, "stopped": 0}
    monitor.stop()
    assert started["stopped"] == 1
