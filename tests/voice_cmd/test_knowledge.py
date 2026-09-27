"""Тесты базы знаний (lib.voice_cmd.knowledge)."""

import json
import os
import time

from lib.voice_cmd.knowledge import (
    CONFIRMED, FINISH, LAYA, START, UNDEFINED, KnowledgeStore,
)


def _sample():
    return {
        "confirmed": {"включи и ютюб": {"kind": "command",
                                        "command": "openyoutube", "hits": 2}},
        "laya": {"тише": {"kind": "command", "command": "volumedown",
                          "hits": 1}},
        "undefined": {"ы ы ы": {"kind": "command", "hits": 0}},
    }


def _write(tmp_path, data):
    path = tmp_path / "knowledge.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


class TestPathsAndState:
    def test_path_for_commands_file(self):
        assert KnowledgeStore.path_for_commands_file(
            os.path.join("x", "targets", "H", "commands.json")
        ) == os.path.join("x", "targets", "H", "knowledge.json")

    def test_enabled_without_file(self):
        assert KnowledgeStore(None).enabled is False

    def test_invalid_file_tolerated(self, tmp_path):
        path = tmp_path / "k.json"
        path.write_text("{битый", encoding="utf-8")
        store = KnowledgeStore(str(path))
        assert store.resolve("включи и ютюб") is None


class TestResolve:
    def test_confirmed_command_resolves(self, tmp_path):
        store = KnowledgeStore(_write(tmp_path, _sample()))
        assert store.resolve("Включи и ЮТЮБ") == "openyoutube"

    def test_laya_not_used_at_runtime(self, tmp_path):
        store = KnowledgeStore(_write(tmp_path, _sample()))
        assert store.resolve("тише") is None

    def test_resolve_event_only_for_start_finish(self, tmp_path):
        store = KnowledgeStore(_write(tmp_path, {
            "confirmed": {
                "я витамины выпил": {"kind": FINISH,
                                     "event": "Завтрак. Принять витамины"},
                "команда": {"kind": "command", "command": "stop"},
            }}))
        assert store.resolve_event("я витамины выпил") == (
            FINISH, "Завтрак. Принять витамины")
        assert store.resolve_event("команда") is None


class TestRecording:
    def test_record_laya_then_confirm(self, tmp_path):
        store = KnowledgeStore(str(tmp_path / "k.json"))
        assert store.record_laya("тише", "volumedown") is True
        assert store.resolve("тише") is None            # laya ещё не решает
        assert store.confirm("тише") is True
        assert store.resolve("тише") == "volumedown"    # confirmed решает

    def test_confirmed_not_downgraded(self, tmp_path):
        store = KnowledgeStore(str(tmp_path / "k.json"))
        store.record_laya("стоп", "stop")
        store.confirm("стоп")
        assert store.record_undefined("стоп") is False  # не понижаем
        assert store.resolve("стоп") == "stop"

    def test_laya_upgrades_over_undefined(self, tmp_path):
        store = KnowledgeStore(str(tmp_path / "k.json"))
        store.record_undefined("тише")
        assert store.record_laya("тише", "volumedown") is True
        assert store.entries(UNDEFINED) == {}
        assert store.entries(LAYA)["тише"]["command"] == "volumedown"

    def test_record_rejects_empty(self, tmp_path):
        store = KnowledgeStore(str(tmp_path / "k.json"))
        assert store.record(LAYA, "", "command") is False
        assert store.record("нет_такого_корзина", "x") is False


class TestBoardOps:
    def test_demote_confirmed_to_undefined(self, tmp_path):
        store = KnowledgeStore(_write(tmp_path, _sample()))
        assert store.demote("включи и ютюб") is True
        assert store.resolve("включи и ютюб") is None
        assert "включи и ютюб" in store.entries(UNDEFINED)

    def test_forget_removes_everywhere(self, tmp_path):
        store = KnowledgeStore(_write(tmp_path, _sample()))
        assert store.forget("тише") is True
        assert store.entries(LAYA) == {}
        assert store.forget("нету") is False

    def test_bump_only_confirmed(self, tmp_path):
        store = KnowledgeStore(_write(tmp_path, _sample()))
        store.bump("включи и ютюб")
        assert store.entries(CONFIRMED)["включи и ютюб"]["hits"] == 3
        store.bump("тише")                              # laya — не бампим
        assert store.entries(LAYA)["тише"]["hits"] == 1

    def test_record_event_start_finish(self, tmp_path):
        store = KnowledgeStore(str(tmp_path / "k.json"))
        store.record(CONFIRMED, "начинаю тренировку", START,
                     event="Тренировка")
        assert store.resolve_event("начинаю тренировку") == (
            START, "Тренировка")

    def test_entries_is_a_copy(self, tmp_path):
        store = KnowledgeStore(_write(tmp_path, _sample()))
        store.entries(LAYA)["тише"]["hits"] = 999
        assert store.entries(LAYA)["тише"]["hits"] == 1

    def test_persisted_to_disk(self, tmp_path):
        path = str(tmp_path / "k.json")
        store = KnowledgeStore(path)
        store.record_laya("тише", "volumedown")
        data = json.loads(open(path, encoding="utf-8").read())
        assert data["laya"]["тише"]["command"] == "volumedown"

    def test_reload_picks_up_changes(self, tmp_path):
        path = str(tmp_path / "k.json")
        store = KnowledgeStore(path)
        store.record_laya("тише", "volumedown")
        path_obj = tmp_path / "k.json"
        path_obj.write_text(json.dumps({"confirmed": {}, "laya": {},
                                        "undefined": {}}), encoding="utf-8")
        future = time.time() + 5
        os.utime(path, (future, future))
        assert store.entries(LAYA) == {}

    def test_missing_file_is_quiet_empty_base(self, tmp_path, capsys):
        """Файла ещё нет — пустая база БЕЗ [Swallowed]-шума."""
        path = tmp_path / "knowledge.json"
        store = KnowledgeStore(str(path))
        assert store.resolve("алиса стоп музыка") is None
        assert store.entries(UNDEFINED) == {}
        assert "Swallowed" not in capsys.readouterr().out
        store.record_undefined("дзынь дзынь")   # первая запись создаёт файл
        assert path.exists()
