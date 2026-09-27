"""Тесты массового распознавания корзины undefined (кнопка «распознать все»)."""

import json
import threading
import time
import urllib.request

import pytest

from lib.voice_cmd import knowledge_review_bulk as kb
from lib.voice_cmd import knowledge_review_server as srv
from lib.voice_cmd.knowledge import LAYA, UNDEFINED, KnowledgeStore
from lib.voice_cmd.knowledge_review_server import make_server


@pytest.fixture
def store(tmp_path):
    s = KnowledgeStore(str(tmp_path / "knowledge.json"))
    for phrase in ("открой я туб", "ы ы ы", "начал тренировку"):
        s.record_undefined(phrase)
    return s


def _http(port, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data,
        headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


class TestRunAll:
    def test_guesses_recorded(self, store, monkeypatch):
        answers = {
            "открой я туб": {"via": "laya", "kind": "command",
                             "command": "openyoutube", "event": ""},
            "ы ы ы": {"via": "none", "kind": "none", "command": "",
                      "event": ""},
            "начал тренировку": {"via": "llm", "kind": "start",
                                 "command": "", "event": "Тренировка"},
        }
        monkeypatch.setattr(kb, "try_recognize",
                            lambda t, c, r: answers[t])
        assert kb.run_all(store, "cfile", {}) == {
            "total": 3, "done": 3, "recognized": 2}
        # распознанное (и Лайей, и LLM) уезжает в корзину laya
        entries = store.entries(LAYA)
        assert entries["открой я туб"]["command"] == "openyoutube"
        assert entries["начал тренировку"]["event"] == "Тренировка"
        undefined = store.entries(UNDEFINED)
        assert "command" not in undefined["ы ы ы"]  # не распознано — здесь
        assert "открой я туб" not in undefined
        assert "начал тренировку" not in undefined

    def test_carried_guess_moves_without_query(self, store, monkeypatch):
        # остатки старого формата: undefined-запись с вписанной командой
        store.record(UNDEFINED, "а лишь тише", "command",
                     command="volumeup")

        def only_new(t, c, r):
            assert t != "а лишь тише", "готовую догадку не переспрашивают"
            return {"via": "none"}

        monkeypatch.setattr(kb, "try_recognize", only_new)
        assert kb.run_all(store, "c", {}) == {
            "total": 4, "done": 4, "recognized": 1}
        assert store.entries(LAYA)["а лишь тише"]["command"] == "volumeup"

    def test_recognize_crash_does_not_stop_run(self, store, monkeypatch):
        def boom(t, c, r):
            if t == "ы ы ы":
                raise RuntimeError("laya dead")
            return {"via": "none"}

        monkeypatch.setattr(kb, "try_recognize", boom)
        assert kb.run_all(store, "c", {}) == {
            "total": 3, "done": 3, "recognized": 0}

    def test_start_rejects_second_run(self, store, monkeypatch):
        monkeypatch.setattr(kb, "try_recognize", lambda t, c, r: {"via":
                                                                  "none"})
        with kb._LOCK:
            kb._STATE["running"] = True
        try:
            assert kb.start(store, "c", {}) is False
        finally:
            with kb._LOCK:
                kb._STATE["running"] = False

    def test_start_completes_in_thread(self, store, monkeypatch):
        monkeypatch.setattr(kb, "try_recognize", lambda t, c, r: {
            "via": "laya", "kind": "command", "command": "stop",
            "event": ""})
        assert kb.start(store, "c", {}) is True
        for _ in range(100):
            if not kb.status()["running"]:
                break
            time.sleep(0.05)
        assert kb.status()["recognized"] == 3


class TestBulkApi:
    def test_start_and_status_endpoints(self, tmp_path, monkeypatch):
        calls = {}

        def fake_start(store, cf, review):
            calls["cf"] = cf
            return True

        monkeypatch.setattr(srv, "bulk_start", fake_start)
        monkeypatch.setattr(srv, "bulk_status",
                            lambda: {"running": False, "recognized": 2})
        store = KnowledgeStore(str(tmp_path / "k.json"))
        cfile = str(tmp_path / "commands.json")
        httpd = make_server(store, cfile, {"port": 0}, 0)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            assert _http(port, "/api/recognize_all", {}) == {"started": True}
            assert calls["cf"] == cfile
            assert _http(port, "/api/recognize_all")["recognized"] == 2
        finally:
            httpd.shutdown()
            httpd.server_close()
