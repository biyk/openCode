"""✕ на доске знаний: вне «Не распознано» он меняет статус, а не удаляет.

Правило пользователя: настоящее удаление живёт только на странице
«Не распознано»; на «Подтверждено» и «Лайе» фраза уезжает в undefined.
"""

import json

import pytest

from lib.voice_cmd.knowledge import CONFIRMED, LAYA, UNDEFINED, KnowledgeStore
from lib.voice_cmd.knowledge_review_board import apply_act
from lib.voice_cmd.knowledge_review_unconfirm import unconfirm_phrase


@pytest.fixture
def cfile(tmp_path):
    """commands.json с одним match-шаблоном («стоп музыка» → stop)."""
    data = {"commands": {"stop": "cmd"},
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


def _commands(cfile):
    return json.loads(open(cfile, encoding="utf-8").read())


class TestUnconfirmConfirmed:
    """✕ на «Подтверждено» — перенос в «Не распознано», ничего не стирается."""

    def test_knowledge_entry_moves_with_payload(self, tmp_path):
        """Баг был: чисто knowledge-фраза удалялась из базы целиком."""
        cfile = str(tmp_path / "commands.json")
        with open(cfile, "w", encoding="utf-8") as f:
            json.dump({"match": {}, "decision": {"enabled": False}}, f,
                      ensure_ascii=False)
        store = _store(tmp_path)
        store.record(CONFIRMED, "закончил гимнастику для плеча",
                     command="taskdone", event="Гимнастика для плеча")
        assert unconfirm_phrase(store, cfile,
                                "закончил гимнастику для плеча") == {
            "match": 0, "moved": True}
        assert "закончил гимнастику для плеча" not in store.entries(CONFIRMED)
        moved = store.entries(UNDEFINED)["закончил гимнастику для плеча"]
        assert moved["command"] == "taskdone"        # переехала целиком
        assert moved["event"] == "Гимнастика для плеча"

    def test_locked_row_lands_in_undefined(self, cfile, tmp_path):
        """Locked-строки в базе нет — для неё заводится новая undefined-запись."""
        store = _store(tmp_path)
        assert unconfirm_phrase(store, cfile, "стоп музыка") == {
            "match": 1, "moved": True}
        assert "стоп музыка" in store.entries(UNDEFINED)
        assert "стоп музыка" not in _commands(cfile).get("match", {}).get(
            "stop", [])

    def test_match_dropped_but_command_kept(self, cfile, tmp_path):
        """Снимается только match: сама команда и прочие секции целы."""
        store = _store(tmp_path)
        unconfirm_phrase(store, cfile, "стоп музыка")
        data = _commands(cfile)
        assert "stop" not in data["match"]           # список опустел → cid снят
        assert data["commands"]["stop"] == "cmd"
        assert data["decision"] == {"enabled": False}

    def test_only_matching_template_removed(self, tmp_path):
        cfile = str(tmp_path / "commands.json")
        with open(cfile, "w", encoding="utf-8") as f:
            json.dump({"match": {"volumeup": ["громче", "сделай громче"]},
                       "decision": {"enabled": False}}, f, ensure_ascii=False)
        store = _store(tmp_path)
        assert unconfirm_phrase(store, cfile, "Громче") == {
            "match": 1, "moved": True}               # ещё и в undefined
        assert _commands(cfile)["match"]["volumeup"] == ["сделай громче"]

    def test_already_undefined_is_not_touched(self, tmp_path):
        """Фраза из «Не распознано» остаётся там же — ✕ её не убирает с доски."""
        cfile = str(tmp_path / "commands.json")
        with open(cfile, "w", encoding="utf-8") as f:
            json.dump({"match": {}, "decision": {"enabled": False}}, f,
                      ensure_ascii=False)
        store = _store(tmp_path)
        store.record(UNDEFINED, "застилал кровать")
        assert unconfirm_phrase(store, cfile, "застилал кровать") == {
            "match": 0, "moved": True}
        assert "застилал кровать" in store.entries(UNDEFINED)


class TestForgetIsBucketScoped:
    """apply_act(forget) удаляет по-настоящему только undefined-записи."""

    def test_confirmed_forget_demotes(self, tmp_path):
        store = _store(tmp_path)
        store.record(CONFIRMED, "тише вода", command="stop")
        assert apply_act(store, {"action": "forget", "text": "тише вода"})
        assert "тише вода" in store.entries(UNDEFINED)

    def test_laya_forget_demotes(self, tmp_path):
        store = _store(tmp_path, {"тише": "volumedown"})
        assert apply_act(store, {"action": "forget", "text": "тише"})
        assert "тише" not in store.entries(LAYA)
        assert "тише" in store.entries(UNDEFINED)

    def test_undefined_forget_deletes(self, tmp_path):
        store = _store(tmp_path)
        store.record(UNDEFINED, "ы ы ы")
        assert apply_act(store, {"action": "forget", "text": "ы ы ы"})
        assert "ы ы ы" not in store.entries(UNDEFINED)

    def test_unknown_phrase_forget_fails(self, tmp_path):
        store = _store(tmp_path)
        assert apply_act(store, {"action": "forget", "text": "нет такой"}) \
            is False
