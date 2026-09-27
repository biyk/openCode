"""Тесты сканера логов доски знаний: фразы, архив, /api/scan."""

import json
import os
import threading
import time
import urllib.request
import zipfile

import pytest

from lib.voice_cmd import knowledge_review_scan as ks
from lib.voice_cmd import knowledge_review_server as srv
from lib.voice_cmd.knowledge import LAYA, UNDEFINED, KnowledgeStore
from lib.voice_cmd.knowledge_review_server import make_server


class _Checker:
    """Фейковый детектор: триггер «алиса», распознано — если ядро в списке."""

    def __init__(self, recognized=()):
        self._recognized = set(recognized)

    def has_trigger(self, text):
        return "алиса" in text

    def core(self, text):
        return text.replace("алиса", "").strip()

    def recognized(self, text):
        return self.core(text) in self._recognized


def _log(d, name, phrases, age_s=3600):
    lines = [f"[2026-09-20 10:00:00] [TEXT] {p}" for p in phrases]
    lines.append("[2026-09-20 10:00:01] [INFO] прочая служебная строка")
    path = d / name
    path.write_text("\n".join(lines), encoding="utf-8")
    old = time.time() - age_s
    os.utime(path, (old, old))
    return str(path)


@pytest.fixture
def logs(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    return d


def _http(port, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data,
        headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


class TestRunScan:
    def test_logs_dir_for(self):
        p = os.path.join("r", "targets", "h", "commands.json")
        assert ks.logs_dir_for(p) == os.path.join("r", "logs")

    def test_adds_unrecognized_and_archives(self, tmp_path, logs):
        _log(logs, "202609201000.log",
             ["алиса открой ю туб", "алиса стоп музыка", "просто текст",
              "алиса открой ю туб"])
        store = KnowledgeStore(str(tmp_path / "k.json"))
        sm = ks.run_scan(store, "x", logs_dir=str(logs),
                         checker=_Checker(["стоп музыка"]))
        assert sm["phrases"] == 3 and sm["added"] == 1  # дедупликация
        assert sm["archived"] == 1 and sm["errors"] == 0
        assert "открой ю туб" in store.entries(UNDEFINED)
        assert "стоп музыка" not in store.entries(UNDEFINED)
        assert not (logs / "202609201000.log").exists()
        with zipfile.ZipFile(logs / "zip" / "20260920.zip") as z:
            assert z.namelist() == ["202609201000.log"]

    def test_skips_active_log(self, tmp_path, logs):
        _log(logs, "202609271351.log", ["алиса хз"], age_s=10)
        store = KnowledgeStore(str(tmp_path / "k.json"))
        sm = ks.run_scan(store, "x", logs_dir=str(logs), checker=_Checker())
        assert sm["total"] == 0 and sm["archived"] == 0
        assert (logs / "202609271351.log").exists()

    def test_known_phrases_untouched(self, tmp_path, logs):
        _log(logs, "202609211200.log", ["алиса открой ю туб"])
        store = KnowledgeStore(str(tmp_path / "k.json"))
        store.record_laya("открой ю туб", "openyoutube")
        sm = ks.run_scan(store, "x", logs_dir=str(logs),
                         checker=_Checker(["открой ю туб"]))
        assert sm["added"] == 0
        assert "открой ю туб" in store.entries(LAYA)
        assert store.entries(UNDEFINED) == {}

    def test_second_log_appends_same_zip(self, tmp_path, logs):
        _log(logs, "202609201000.log", ["алиса раз"])
        _log(logs, "202609201100.log", ["алиса два"])
        store = KnowledgeStore(str(tmp_path / "k.json"))
        ks.run_scan(store, "x", logs_dir=str(logs), checker=_Checker())
        with zipfile.ZipFile(logs / "zip" / "20260920.zip") as z:
            assert sorted(z.namelist()) == ["202609201000.log",
                                            "202609201100.log"]

    def test_start_status_thread(self, tmp_path, logs):
        _log(logs, "202609201000.log", ["алиса раз"])
        store = KnowledgeStore(str(tmp_path / "k.json"))
        assert ks.start(store, "x", logs_dir=str(logs),
                        checker=_Checker()) is True
        for _ in range(100):
            if not ks.status()["running"]:
                break
            time.sleep(0.05)
        assert ks.status()["added"] == 1
        assert "раз" in store.entries(UNDEFINED)


class TestScanApi:
    def test_scan_start_and_status_via_http(self, tmp_path, monkeypatch):
        calls = {}

        def fake_start(store, cf, logs_dir="", checker=None):
            calls["cf"] = cf
            return True

        monkeypatch.setattr(srv, "scan_start", fake_start)
        monkeypatch.setattr(srv, "scan_status",
                            lambda: {"running": True, "total": 3})
        store = KnowledgeStore(str(tmp_path / "k.json"))
        cfile = str(tmp_path / "commands.json")
        httpd = make_server(store, cfile, {"port": 0}, 0)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            assert _http(port, "/api/scan", {}) == {"started": True}
            assert calls["cf"] == cfile
            assert _http(port, "/api/scan")["running"] is True
        finally:
            httpd.shutdown()
            httpd.server_close()
