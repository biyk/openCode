"""Тесты массового распознавания undefined (кнопка «распознать все») и его
журнала: след каждой фразы доступен `log_text()` сразу после прогона."""

import json
import threading
import time
import urllib.request

import pytest

from lib.voice_cmd import knowledge_review_bulk as kb
from lib.voice_cmd import knowledge_review_server as srv
from lib.voice_cmd.knowledge import LAYA, UNDEFINED, KnowledgeStore
from lib.voice_cmd.knowledge_review_server import make_server

TITLES = ["Пальцевая гимнастика"]


@pytest.fixture
def store(tmp_path):
    s = KnowledgeStore(str(tmp_path / "knowledge.json"))
    for phrase in ("открой я туб", "ы ы ы", "начал тренировку"):
        s.record_undefined(phrase)
    return s


@pytest.fixture(autouse=True)
def no_sheets(monkeypatch):
    """Список задач таблицы в тестах не читаем (живой Google Sheets)."""
    calls = []
    monkeypatch.setattr(kb, "sheet_task_titles",
                        lambda: (calls.append(1), TITLES)[1])
    return calls


def _http(port, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data,
        headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def _traced(**kw):
    """Ответ try_recognize с обязательным следом фразы."""
    return dict({"via": "none", "kind": "none", "command": "", "event": "",
                 "trace": "фраза:\nфаза 1\t—"}, **kw)


class TestRunAll:
    def test_guesses_recorded(self, store, monkeypatch):
        answers = {
            "открой я туб": _traced(via="laya", kind="command",
                                    command="openyoutube"),
            "ы ы ы": _traced(),
            "начал тренировку": _traced(via="llm", kind="start",
                                        event="Тренировка"),
        }
        monkeypatch.setattr(kb, "try_recognize",
                            lambda t, c, r, ti: answers[t])
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

    def test_log_holds_every_phrase_trace(self, store, monkeypatch):
        answers = {
            "открой я туб": _traced(via="laya", kind="command",
                                    command="openyoutube",
                                    trace="фраза:\tоткрой я туб\nфаза 1\tда"),
            "ы ы ы": _traced(trace="фраза:\tы ы ы\nфаза 1\tмимо"),
            "начал тренировку": _traced(via="llm", kind="finish",
                                        event="Тренировка",
                                        trace="фраза:\tначал тренировку"),
        }
        monkeypatch.setattr(kb, "try_recognize",
                            lambda t, c, r, ti: answers[t])
        kb.run_all(store, "cfile", {})
        log = kb.log_text()
        assert "=== прогон " in log and "фраз 3, распознано 2 ===" in log
        for phrase in answers:
            assert answers[phrase]["trace"] in log
        assert log.count("фраза:") == 3

    def test_titles_read_once_per_run(self, store, monkeypatch, no_sheets):
        monkeypatch.setattr(kb, "try_recognize",
                            lambda t, c, r, ti: _traced())
        kb.run_all(store, "c", {})
        assert len(no_sheets) == 1     # один read на прогон, не на фразу

    def test_empty_run_skips_sheets(self, tmp_path, monkeypatch, no_sheets):
        s = KnowledgeStore(str(tmp_path / "k.json"))
        monkeypatch.setattr(kb, "try_recognize",
                            lambda t, c, r, ti: _traced())
        assert kb.run_all(s, "c", {}) == {"total": 0, "done": 0,
                                          "recognized": 0}
        assert not no_sheets

    def test_carried_guess_moves_without_query(self, store, monkeypatch):
        # остатки старого формата: undefined-запись с вписанной командой
        store.record(UNDEFINED, "а лишь тише", "command",
                     command="volumeup")

        def only_new(t, c, r, ti):
            assert t != "а лишь тише", "готовую догадку не переспрашивают"
            return _traced()

        monkeypatch.setattr(kb, "try_recognize", only_new)
        assert kb.run_all(store, "c", {}) == {
            "total": 4, "done": 4, "recognized": 1}
        assert store.entries(LAYA)["а лишь тише"]["command"] == "volumeup"
        # в журнале перенесённая догадка помечена как не опрашиваемая
        assert "готовая догадка" in kb.log_text()

    def test_recognize_crash_does_not_stop_run(self, store, monkeypatch):
        def boom(t, c, r, ti):
            if t == "ы ы ы":
                raise RuntimeError("laya dead")
            return _traced()

        monkeypatch.setattr(kb, "try_recognize", boom)
        assert kb.run_all(store, "c", {}) == {
            "total": 3, "done": 3, "recognized": 0}
        assert "ошибка: laya dead" in kb.log_text()

    def test_start_rejects_second_run(self, store, monkeypatch):
        monkeypatch.setattr(kb, "try_recognize",
                            lambda t, c, r, ti: _traced())
        with kb._LOCK:
            kb._STATE["running"] = True
        try:
            assert kb.start(store, "c", {}) is False
        finally:
            with kb._LOCK:
                kb._STATE["running"] = False

    def test_start_completes_in_thread(self, store, monkeypatch):
        monkeypatch.setattr(kb, "try_recognize", lambda t, c, r, ti: _traced(
            via="laya", kind="command", command="stop"))
        assert kb.start(store, "c", {}) is True
        for _ in range(100):
            if not kb.status()["running"]:
                break
            time.sleep(0.05)
        assert kb.status()["recognized"] == 3
        assert kb.log_text().startswith("=== прогон")


class TestBulkApi:
    def test_start_and_status_endpoints(self, tmp_path, monkeypatch):
        calls = {}

        def fake_start(store, cf, review):
            calls["cf"] = cf
            return True

        monkeypatch.setattr(srv, "bulk_start", fake_start)
        monkeypatch.setattr(srv, "bulk_status",
                            lambda: {"running": False, "done": 3, "total": 3,
                                     "recognized": 2})
        monkeypatch.setattr(srv, "bulk_log", lambda: "фраза:\tтест")
        store = KnowledgeStore(str(tmp_path / "k.json"))
        cfile = str(tmp_path / "commands.json")
        httpd = make_server(store, cfile, {"port": 0}, 0)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            assert _http(port, "/api/recognize_all", {}) == {"started": True}
            assert calls["cf"] == cfile
            assert _http(port, "/api/recognize_all")["recognized"] == 2
            assert _http(port, "/api/recognize_log") == {
                "log": "фраза:\tтест", "running": False, "total": 3,
                "done": 3}
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_log_route_survives_partial_status(self, tmp_path, monkeypatch):
        # просроченный/незаполненный прогресс не роняет попап журнала
        monkeypatch.setattr(srv, "bulk_status", lambda: {"recognized": 0})
        monkeypatch.setattr(srv, "bulk_log", lambda: "")
        store = KnowledgeStore(str(tmp_path / "k.json"))
        httpd = make_server(store, str(tmp_path / "commands.json"),
                            {"port": 0}, 0)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            assert _http(port, "/api/recognize_log") == {
                "log": "", "running": False, "total": 0, "done": 0}
        finally:
            httpd.shutdown()
            httpd.server_close()
