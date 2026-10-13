from lib.monitor import probes
from lib.monitor.registry import IDLE, WORKING


def test_external_returns_three_services(monkeypatch):
    monkeypatch.setattr(probes, "_http_ok", lambda *a, **k: True)
    out = probes.external()
    ids = {s["id"] for s in out}
    assert ids == {"laya", "browser", "board"}
    assert all(s["state"] == WORKING for s in out)


def test_probe_laya_working_and_idle(monkeypatch):
    monkeypatch.setattr(probes, "_http_ok", lambda *a, **k: True)
    assert probes.probe_laya()["state"] == WORKING
    monkeypatch.setattr(probes, "_http_ok", lambda *a, **k: False)
    assert probes.probe_laya()["state"] == IDLE


def test_probe_cdp_idle_when_down(monkeypatch):
    monkeypatch.setattr(probes, "_http_ok", lambda *a, **k: False)
    res = probes.probe_cdp(59999)
    assert res["state"] == IDLE
    assert "не отвечает" in res["detail"]
