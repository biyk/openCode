"""Тесты вкладки монитора на сервере доски (`/api/monitor`, `GET /`).

Панель «Сервисы» живёт тем же процессом, что и база знаний: проверяем, что
эндпоинт отдаёт снимок реестра, а страница — с вкладкой. Пробу портов
подменяем, чтобы тест не ходил в сеть и не зависал на таймаутах.
"""

import json
import threading
import urllib.request

from lib.voice_cmd import knowledge_review_server as srv
from lib.voice_cmd.knowledge import KnowledgeStore
from lib.voice_cmd.knowledge_review_server import make_server

_SNAPSHOT = {"ts": 1.0, "stale": False, "age_s": 0.5,
             "services": [{"id": "stt", "name": "Слушалка",
                           "state": "working", "detail": ""},
                          {"id": "omniroute", "name": "OmniRouter (LLM)",
                           "state": "idle", "detail": "порт открыт"}]}


def _serve(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "monitor_status", lambda: dict(_SNAPSHOT))
    httpd = make_server(KnowledgeStore(str(tmp_path / "k.json")),
                        str(tmp_path / "commands.json"), {"port": 0}, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def _get(port, path):
    return urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5)


def test_monitor_endpoint_returns_snapshot(tmp_path, monkeypatch):
    httpd, port = _serve(tmp_path, monkeypatch)
    try:
        with _get(port, "/api/monitor") as r:
            body = json.loads(r.read().decode("utf-8"))
        assert body["stale"] is False
        ids = [s["id"] for s in body["services"]]
        assert "stt" in ids and "omniroute" in ids
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_page_carries_services_tab(tmp_path, monkeypatch):
    httpd, port = _serve(tmp_path, monkeypatch)
    try:
        with _get(port, "/") as r:
            html = r.read().decode("utf-8")
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert "/api/monitor" in html
    assert 'sec.id="t-services"' in html
    assert html.count("</body>") == 1


def test_page_tab_does_not_break_board_api(tmp_path, monkeypatch):
    """Вкладка не должна отнимать у доски её собственные маршруты."""
    httpd, port = _serve(tmp_path, monkeypatch)
    try:
        with _get(port, "/api/ping") as r:
            assert json.loads(r.read().decode("utf-8")) == {"ok": True}
    finally:
        httpd.shutdown()
        httpd.server_close()
