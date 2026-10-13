import json
import threading
import urllib.request

from lib.monitor import dashboard


def _fetch(url):
    with urllib.request.urlopen(url, timeout=2) as r:
        return r.status, r.read()


def test_server_status_and_page(monkeypatch):
    fake = {"stale": False, "age_s": 0.5,
            "services": [{"id": "stt", "name": "X", "state": "working",
                          "detail": ""}]}
    monkeypatch.setattr(dashboard, "collect", lambda: fake)
    httpd = dashboard.make_server(0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        code, body = _fetch(f"http://127.0.0.1:{port}/api/ping")
        assert code == 200 and json.loads(body)["ok"] is True
        code, body = _fetch(f"http://127.0.0.1:{port}/api/status")
        assert json.loads(body)["services"][0]["id"] == "stt"
        code, body = _fetch(f"http://127.0.0.1:{port}/")
        assert code == 200 and "Монитор" in body.decode("utf-8")
        assert dashboard.is_up(port) is True
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=3)


def test_is_up_false_on_closed_port():
    assert dashboard.is_up(59998) is False
