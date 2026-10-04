"""Тесты обучения при «✓ подтвердить» на доске (apply_act confirm → learn).

Разнесено с test_knowledge_review.py (потолок 200 строк): здесь только ветки
обучения — ключ в commands.json.match и synonym в базе знаний.
"""

import json

from lib.voice_cmd.knowledge import CONFIRMED, KnowledgeStore
from lib.voice_cmd.knowledge_review_board import (
    apply_act, delete_confirmed_phrase,
)


def _store(tmp_path, seed_laya=None):
    store = KnowledgeStore(str(tmp_path / "knowledge.json"))
    for text, cid in (seed_laya or {}).items():
        store.record_laya(text, cid)
    return store


class TestConfirmLearning:
    def test_confirm_without_commands_file_skips_learn(self, tmp_path):
        # back-compat: старый вызов apply_act(store, act) не трогает match.
        store = _store(tmp_path, {"тише": "volumedown"})
        assert apply_act(store, {"action": "confirm", "text": "тише"}) is True
        assert "тише" in store.entries(CONFIRMED)

    def test_confirm_end_to_end_learns_key_and_synonym(self, tmp_path):
        cfile = str(tmp_path / "commands.json")
        with open(cfile, "w", encoding="utf-8") as f:
            json.dump({"commands": {"taskdone": 'x "{{text}}"'},
                       "match": {}, "decision": {"enabled": False}},
                      f, ensure_ascii=False)
        store = _store(tmp_path, {"закончил пальцами гимнастику": "taskdone"})
        assert apply_act(store, {
            "action": "update", "text": "закончил пальцами гимнастику",
            "kind": "command", "command": "taskdone",
            "event": "Пальцевая гимнастика"}, cfile)
        assert apply_act(store, {
            "action": "confirm", "text": "закончил пальцами гимнастику",
            "key": "закончил"}, cfile)
        data = json.loads(open(cfile, encoding="utf-8").read())
        assert data["match"]["taskdone"] == ["закончил"]
        assert store.resolve_synonym("пальцами гимнастику") == \
            "Пальцевая гимнастика"

    def test_confirm_passes_key_to_learn(self, tmp_path, monkeypatch):
        from lib.voice_cmd import knowledge_review_board as board
        seen = []
        monkeypatch.setattr(board, "learn_from_confirm", lambda *a: seen.append(a))
        store = _store(tmp_path)
        store.confirm = lambda text: True            # не трогаем корзины
        ok = board.apply_act(store, {"action": "confirm", "text": "фразу",
                                     "key": "кл"}, "/c.json")
        assert ok is True
        assert seen == [(store, "/c.json", "фразу", "кл")]


class TestUpdateRegistersKey:
    """«сохранить» на confirmed с key → register_key в commands.json."""

    def _cfile(self, tmp_path, match=None):
        cfile = str(tmp_path / "commands.json")
        with open(cfile, "w", encoding="utf-8") as f:
            json.dump({"commands": {"taskdone": 'x "{{text}}"'},
                       "match": match or {}, "decision": {"enabled": False}},
                      f, ensure_ascii=False)
        return cfile

    def test_update_confirmed_registers_key(self, tmp_path):
        cfile = self._cfile(tmp_path, {"taskdone": ["закончил задачу"]})
        store = KnowledgeStore(str(tmp_path / "k.json"))
        store.record(CONFIRMED, "закончен глобальных задач",
                     command="taskdone", event="Глобальные задачи")
        ok = apply_act(store, {
            "action": "update", "text": "закончен глобальных задач",
            "kind": "command", "command": "taskdone",
            "event": "глобальных задач", "key": "закончен"}, cfile)
        assert ok is True
        data = json.loads(open(cfile, encoding="utf-8").read())
        assert "закончен" in data["match"]["taskdone"]

    def test_update_non_confirmed_skips_register(self, tmp_path):
        cfile = self._cfile(tmp_path)
        store = KnowledgeStore(str(tmp_path / "k.json"))
        store.record_laya("запусти тест", "taskstart")
        ok = apply_act(store, {
            "action": "update", "text": "запусти тест",
            "kind": "command", "command": "taskstart",
            "event": "тест", "key": "запусти"}, cfile)
        assert ok is True
        data = json.loads(open(cfile, encoding="utf-8").read())
        assert "taskstart" not in data.get("match", {})

    def test_update_empty_key_noop(self, tmp_path):
        cfile = self._cfile(tmp_path)
        store = KnowledgeStore(str(tmp_path / "k.json"))
        store.record(CONFIRMED, "открой базу", command="openbd")
        apply_act(store, {
            "action": "update", "text": "открой базу",
            "kind": "command", "command": "openbd",
            "event": "", "key": ""}, cfile)
        data = json.loads(open(cfile, encoding="utf-8").read())
        assert "openbd" not in data.get("match", {})


class TestPurgeKnowledgeOnly:
    def test_purge_knowledge_only_forgets(self, tmp_path):
        """✕ на confirmed для чисто knowledge-фразы (нет match) → forget."""
        cfile = str(tmp_path / "commands.json")
        with open(cfile, "w", encoding="utf-8") as f:
            json.dump({"match": {}, "decision": {"enabled": False}},
                      f, ensure_ascii=False)
        store = KnowledgeStore(str(tmp_path / "k.json"))
        store.record(CONFIRMED, "страна фри оку", command="taskdone",
                     event="Струна Фуриоку")
        res = delete_confirmed_phrase(store, cfile, "страна фри оку")
        assert res == {"match": 0, "knowledge": True}
        assert "страна фри оку" not in store.entries(CONFIRMED)
