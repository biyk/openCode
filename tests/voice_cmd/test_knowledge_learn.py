"""Тесты обучения с доски (knowledge_learn): ключ → match, задача → synonym.

register_key кладёт фразу-триггер в commands.json["match"][cid] (дедуп по
normalize_core, атомарная запись, другие секции не тронуты); learn разводит
коллекторы: не-задачная команда пишет только ключ, задача — ещё и синоним.
"""

import json

import pytest

from lib.voice_cmd.knowledge import FINISH, KnowledgeStore
from lib.voice_cmd.knowledge_learn import _fragment, learn, register_key


@pytest.fixture
def cfile(tmp_path):
    data = {"commands": {"taskdone": 'x "{{text}}"', "stop": "y"},
            "match": {"stop": ["стоп музыка"]},
            "decision": {"enabled": False}}
    path = tmp_path / "commands.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _read(cfile):
    with open(cfile, encoding="utf-8") as f:
        return json.load(f)


class TestRegisterKey:
    def test_adds_new_key(self, cfile):
        assert register_key(cfile, "taskdone", "закончил") is True
        assert _read(cfile)["match"]["taskdone"] == ["закончил"]

    def test_dedup_by_normalize_core(self, cfile):
        assert register_key(cfile, "taskdone", "закончил задачу") is True
        assert register_key(cfile, "taskdone", "Закончил   Задачу") is False
        assert _read(cfile)["match"]["taskdone"] == ["закончил задачу"]

    def test_empty_key_is_noop(self, cfile):
        assert register_key(cfile, "taskdone", "   ") is False
        assert "taskdone" not in _read(cfile)["match"]

    def test_preserves_other_sections(self, cfile):
        assert register_key(cfile, "taskdone", "закончил") is True
        data = _read(cfile)
        assert data["commands"]["stop"] == "y"
        assert data["match"]["stop"] == ["стоп музыка"]
        assert data["decision"] == {"enabled": False}


class TestFragment:
    def test_strips_key_prefix(self):
        assert _fragment("закончил пальцами гимнастику", "закончил") == \
            "пальцами гимнастику"

    def test_no_key_keeps_whole_phrase(self):
        assert _fragment("пальцами гимнастику", "") == "пальцами гимнастику"


class TestLearn:
    def test_task_registers_key_and_synonym(self, cfile, tmp_path):
        store = KnowledgeStore(str(tmp_path / "k.json"))
        assert learn(store, cfile, text="закончил пальцами гимнастику",
                     command="taskdone", kind="command",
                     event="Пальцевая гимнастика", key="закончил") is True
        assert _read(cfile)["match"]["taskdone"] == ["закончил"]
        assert store.resolve_synonym("пальцами гимнастику") == \
            "Пальцевая гимнастика"

    def test_non_task_command_writes_key_only(self, cfile, tmp_path):
        store = KnowledgeStore(str(tmp_path / "k.json"))
        assert learn(store, cfile, text="стоп музыка", command="stop",
                     kind="command", event=None, key="стоп") is True
        assert _read(cfile)["match"]["stop"] == ["стоп музыка", "стоп"]
        assert store.synonyms() == {}

    def test_finish_kind_synonym_without_command(self, cfile, tmp_path):
        store = KnowledgeStore(str(tmp_path / "k.json"))
        learn(store, cfile, text="я витамины выпил", command=None,
              kind=FINISH, event="Завтрак", key="")
        assert store.resolve_synonym("я витамины выпил") == "Завтрак"
        assert "taskdone" not in _read(cfile).get("match", {})

    def test_auto_detect_key_first_word(self, cfile, tmp_path):
        """key="" + taskdone → auto-detect first word as key, fragment synonym."""
        store = KnowledgeStore(str(tmp_path / "k.json"))
        assert learn(store, cfile, text="закончил гимнастика ты плеча",
                     command="taskdone", kind="command",
                     event="Гимнастика для плеча", key="") is True
        assert "закончил" in _read(cfile)["match"]["taskdone"]
        assert store.resolve_synonym("гимнастика ты плеча") == \
            "Гимнастика для плеча"

    def test_auto_detect_key_uses_existing_match_prefix(self, tmp_path):
        """If an existing match phrase IS a prefix of text, use it (longer)."""
        cfile = str(tmp_path / "commands.json")
        json.dump({"commands": {"taskdone": 'x "{{text}}"'},
                   "match": {"taskdone": ["закончил задачу"]},
                   "descriptions": {}},
                  open(cfile, "w", encoding="utf-8"), ensure_ascii=False)
        store = KnowledgeStore(str(tmp_path / "k.json"))
        # text starts with "закончил задачу" — detected as key via existing match
        learn(store, cfile, text="закончил задачу уборка",
              command="taskdone", kind="command",
              event="Генеральная уборка", key="")
        assert store.resolve_synonym("уборка") == "Генеральная уборка"
