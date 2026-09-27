"""Тесты доски «проверка знаний»: конфиг, операции доски, HTTP-API.

Распознавание фразы — в test_knowledge_review_recognize.py,
подсказка task-complete (задачи real_life_tasks) — в
test_knowledge_review_tasks.py.
"""

import json
import threading
import urllib.request

import pytest

from lib.voice_cmd.knowledge import CONFIRMED, LAYA, UNDEFINED, KnowledgeStore
from lib.voice_cmd.knowledge_review_recognize import load_review, save_review
from lib.voice_cmd.knowledge_review_board import (
    apply_act, board_snapshot, delete_confirmed_phrase, laya_status,
)
from lib.voice_cmd.knowledge_review_server import make_server


@pytest.fixture
def cfile(tmp_path):
    """Временный commands.json (команды, match-шаблоны, пустой decision)."""
    data = {"commands": {"stop": "cmd", "volumedown": "cmd2"},
            "sequences": {"news": {"steps": ["stop"]}},
            "descriptions": {"stop": "остановить медиа"},
            "match": {"stop": ["стоп музыка"]},
            "decision": {"enabled": False}}
    path = tmp_path / "commands.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _store(tmp_path, seed_laya=None):
    store = KnowledgeStore(str(tmp_path / "knowledge.json"))
    for text, cid in (seed_laya or {}).items():
        store.record_laya(text, cid)
    return store


def _http(port, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data,
        headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


class TestReviewConfig:
    def test_defaults_without_file(self, cfile):
        assert load_review(cfile)["port"] == 8765

    def test_save_reload_roundtrip(self, cfile):
        assert save_review(cfile, {"llm_model": "m2", "port": 9000,
                                   "мусор": 1}) is True
        cfg = load_review(cfile)
        assert cfg["llm_model"] == "m2" and cfg["port"] == 9000
        assert "мусор" not in cfg


class TestBoardAndActs:
    def test_confirmed_locks_match_and_edits_knowledge(self, cfile, tmp_path):
        store = _store(tmp_path)
        store.record(CONFIRMED, "включи и ютюб", command="openyoutube")
        conf = board_snapshot(store, cfile,
                              {"port": 8765})["boards"][CONFIRMED]
        # match-шаблон из commands.json — locked read-only
        assert conf["стоп музыка"]["locked"] is True
        assert conf["стоп музыка"]["command"] == "stop"
        assert conf["стоп музыка"]["source"] == "commands.json"
        # подтверждённая запись знаний — редактируемая (не locked)
        assert "locked" not in conf["включи и ютюб"]
        assert conf["включи и ютюб"]["source"] == "знания"

    def test_board_snapshot(self, cfile, tmp_path):
        store = _store(tmp_path, {"тише": "volumedown"})
        snap = board_snapshot(store, cfile, {"port": 8765})
        assert "тише" in snap["boards"][LAYA]
        assert set(snap["commands"]) == {"stop", "volumedown", "news"}
        assert snap["port"] == 8765

    def test_apply_act_moves_buckets(self, cfile, tmp_path):
        store = _store(tmp_path, {"тише": "volumedown"})
        assert apply_act(store, {"action": "confirm", "text": "тише"})
        assert "тише" in store.entries(CONFIRMED)
        assert apply_act(store, {"action": "demote", "text": "тише"})
        assert "тише" in store.entries(UNDEFINED)
        assert apply_act(store, {"action": "forget", "text": "тише"})
        assert apply_act(store, {"action": "нет", "text": "тише"}) is False

    def test_update_keeps_bucket_and_edits(self, tmp_path):
        store = _store(tmp_path, {"start finish": "stop"})
        assert apply_act(store, {"action": "update", "text": "start finish",
                                 "kind": "finish", "event": "Завтрак"})
        entry = store.entries(LAYA)["start finish"]
        assert entry["kind"] == "finish" and entry["event"] == "Завтрак"
        assert "command" not in entry

    def test_reset_on_laya_returns_to_undefined(self, tmp_path):
        # ✕ на вкладке «Лайя»: снимает догадку ИИ, но не удаляет из базы.
        store = _store(tmp_path, {"тише": "volumedown"})
        assert apply_act(store, {"action": "reset", "text": "тише"})
        assert "тише" not in store.entries(LAYA)
        assert "тише" in store.entries(UNDEFINED)

    def test_reset_ignores_non_laya(self, tmp_path):
        store = _store(tmp_path)
        store.record(UNDEFINED, "ы ы ы")
        store.record(CONFIRMED, "стоп музыка", command="stop")
        assert apply_act(store, {"action": "reset", "text": "ы ы ы"}) is False
        assert apply_act(store, {"action": "reset",
                                 "text": "стоп музыка"}) is False
        assert "ы ы ы" in store.entries(UNDEFINED)
        assert "стоп музыка" in store.entries(CONFIRMED)

    def test_laya_status_disabled(self, cfile):
        assert laya_status(cfile) == {"enabled": False, "url": "",
                                      "up": False}

    def test_purge_removes_from_both_stores(self, cfile, tmp_path):
        # confirmed-мусор чистится и из commands.json.match, и из знаний.
        store = _store(tmp_path)
        store.record(CONFIRMED, "стоп музыка", command="stop")
        assert delete_confirmed_phrase(store, cfile, "стоп музыка") == {
            "knowledge": True, "match": 1}
        assert "стоп музыка" not in store.entries(CONFIRMED)
        data = json.loads(open(cfile, encoding="utf-8").read())
        assert "stop" not in data["match"]          # список опустел → cid снят
        assert data["commands"]["stop"] == "cmd"     # команда не тронута
        assert data["decision"] == {"enabled": False}

    def test_purge_removes_only_matching_template(self, tmp_path):
        cfile = str(tmp_path / "commands.json")
        with open(cfile, "w", encoding="utf-8") as f:
            json.dump({"match": {"volumeup": ["громче", "сделай громче"]},
                       "decision": {"enabled": False}},
                      f, ensure_ascii=False)
        store = _store(tmp_path)
        assert delete_confirmed_phrase(store, cfile, "Громче") == {
            "knowledge": False, "match": 1}
        data = json.loads(open(cfile, encoding="utf-8").read())
        assert data["match"]["volumeup"] == ["сделай громче"]


class TestHttpApi:
    def test_ping_board_act(self, cfile, tmp_path):
        store = _store(tmp_path, {"тише": "volumedown"})
        httpd = make_server(store, cfile, {"port": 0, "llm_url": ""}, 0)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            assert _http(port, "/api/ping") == {"ok": True}
            assert "тише" in _http(port, "/api/board")["boards"][LAYA]
            assert _http(port, "/api/act",
                         {"action": "confirm", "text": "тише"}) == {"ok": True}
            assert "тише" in store.entries(CONFIRMED)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_purge_locked_phrase_via_api(self, cfile, tmp_path):
        store = _store(tmp_path)
        httpd = make_server(store, cfile, {"port": 0}, 0)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            conf = _http(port, "/api/board")["boards"][CONFIRMED]
            assert "стоп музыка" in conf          # locked-строка есть
            r = _http(port, "/api/act",
                      {"action": "purge", "text": "стоп музыка"})
            assert r["ok"] is True and r["match"] == 1
            conf = _http(port, "/api/board")["boards"][CONFIRMED]
            assert "стоп музыка" not in conf      # исчезла со снимка
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_settings_saved_via_api(self, cfile, tmp_path):
        store = _store(tmp_path)
        httpd = make_server(store, cfile, {"port": 0}, 0)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            r = _http(port, "/api/settings",
                      {"llm_url": "http://x:1234/v1", "llm_model": "mm"})
            assert r == {"ok": True}
            assert load_review(cfile)["llm_model"] == "mm"
        finally:
            httpd.shutdown()
            httpd.server_close()
