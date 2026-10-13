import os
import time

from lib.monitor import heartbeat, launch
from lib.monitor.registry import ServiceRegistry, WORKING


class _Matcher:
    def __init__(self, cfg):
        self._cfg = cfg

    def get_monitor_config(self):
        return self._cfg


class _Out:
    def print_info(self, message):
        pass

    def print_error(self, message):
        pass


def test_start_monitor_disabled_returns_none():
    got = launch.start_monitor(_Matcher({"enabled": False}), output=_Out(),
                               registry=ServiceRegistry())
    assert got is None


def test_start_monitor_writes_heartbeat(tmp_path, monkeypatch):
    hb = str(tmp_path / "hb.json")
    monkeypatch.setattr(heartbeat, "default_path", lambda: hb)
    reg = ServiceRegistry()
    reg.report("stt", "Слушалка", WORKING)
    writer = launch.start_monitor(
        _Matcher({"enabled": True, "auto_open": False}), output=_Out(),
        registry=reg)
    deadline = time.time() + 2
    while time.time() < deadline and not os.path.exists(hb):
        time.sleep(0.05)
    writer.stop()
    assert os.path.exists(hb)


def test_start_monitor_broken_matcher_defaults_enabled(
        tmp_path, monkeypatch):
    # Matcher без get_monitor_config → config {} → enabled default True,
    # auto_open default True, но dashboard.launch перехулиганен, без браузера.
    hb = str(tmp_path / "hb.json")
    monkeypatch.setattr(heartbeat, "default_path", lambda: hb)

    class _Boom:
        def get_monitor_config(self):
            raise RuntimeError("нет секции")

    launched = {"hit": False}

    def _fake_launch(port, output=None):
        launched["hit"] = True

    import lib.monitor.dashboard as dash
    monkeypatch.setattr(dash, "launch", _fake_launch)
    writer = launch.start_monitor(_Boom(), output=_Out(),
                                  registry=ServiceRegistry())
    assert writer is not None
    assert launched["hit"] is True
    writer.stop()
