from lib.monitor import probes
from lib.monitor.registry import IDLE, WORKING


def test_external_returns_four_services(monkeypatch):
    monkeypatch.setattr(probes, "http_ok", lambda *a, **k: True)
    out = probes.external()
    ids = {s["id"] for s in out}
    assert ids == {"laya", "browser", "board", "omniroute"}
    assert all(s["state"] == WORKING for s in out)


def test_probe_laya_working_and_idle(monkeypatch):
    monkeypatch.setattr(probes, "http_ok", lambda *a, **k: True)
    assert probes.probe_laya()["state"] == WORKING
    monkeypatch.setattr(probes, "http_ok", lambda *a, **k: False)
    assert probes.probe_laya()["state"] == IDLE


def test_probe_cdp_idle_when_down(monkeypatch):
    monkeypatch.setattr(probes, "http_ok", lambda *a, **k: False)
    res = probes.probe_cdp(59999)
    assert res["state"] == IDLE
    assert "не отвечает" in res["detail"]


def test_probe_omni_hits_health_endpoint(monkeypatch):
    seen = {}

    def _fake(url, timeout=None):
        seen["url"] = url
        return True

    monkeypatch.setattr(probes, "http_ok", _fake)
    assert probes.probe_omni("http://127.0.0.1:20128")["state"] == WORKING
    assert seen["url"] == "http://127.0.0.1:20128/healthz"


def test_probe_omni_idle_mentions_watchdog(monkeypatch):
    monkeypatch.setattr(probes, "http_ok", lambda *a, **k: False)
    res = probes.probe_omni()
    assert res["state"] == IDLE
    assert "смотрител" in res["detail"]


def test_http_ok_swallows_closed_port():
    """Порт 59999 никто не слушает: проба обязана вернуть False, а не упасть."""
    got = probes.http_ok("http://127.0.0.1:59999/api/ping", timeout=0.2)
    assert got is False
