"""Тесты поля `added` в базе знаний: дата первого появления записи.

Смысл: доска должна различать «свежак» и «давно в базе» — для сортировки
и фильтра «что нового». Правила:
- новая запись → сегодняшняя дата;
- перезапись той же фразы (record/_move) → исходная дата сохраняется;
- миграние при загрузке: у старых записей без поля ставим сегодняшнюю;
- migration идемпотентна — второй проход не трогает файл;
- synonyms — top-level карта, поле `added` ей не нужно.
"""

import json
import os
import time

from lib.voice_cmd.knowledge import (
    COMMAND, CONFIRMED, LAYA, UNDEFINED, KnowledgeStore, today_str,
)


def _write(tmp_path, data):
    path = tmp_path / "knowledge.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


class TestAddedDate:
    def test_record_sets_today(self, tmp_path):
        store = KnowledgeStore(str(tmp_path / "k.json"))
        store.record(LAYA, "тише", COMMAND, command="volumedown")
        entry = store.entries(LAYA)["тише"]
        assert entry["added"] == today_str()

    def test_record_preserves_added_on_overwrite(self, tmp_path):
        """Перезапись той же фразы не сдвигает дату — она про первый вход."""
        path = str(tmp_path / "k.json")
        store = KnowledgeStore(path)
        store.record(LAYA, "тише", COMMAND, command="volumedown")
        first = store.entries(LAYA)["тише"]["added"]
        # Имитируем «запись была давно»: правим файл напрямую.
        data = json.loads(open(path, encoding="utf-8").read())
        data[LAYA]["тише"]["added"] = "2020-01-01"
        open(path, "w", encoding="utf-8").write(json.dumps(data))
        future = time.time() + 5
        os.utime(path, (future, future))
        store.reload()
        assert store.record(LAYA, "тише", COMMAND, command="volumeup")
        assert store.entries(LAYA)["тише"]["added"] == "2020-01-01"
        assert first != "2020-01-01"

    def test_migrate_fills_added_on_load(self, tmp_path):
        """Старые записи без `added` получают сегодняшнюю дату при загрузке."""
        legacy = {CONFIRMED: {"стоп": {"kind": COMMAND, "command": "stop"}},
                  LAYA: {"тише": {"kind": COMMAND, "command": "volumedown"}},
                  UNDEFINED: {}}
        store = KnowledgeStore(_write(tmp_path, legacy))
        assert store.entries(CONFIRMED)["стоп"]["added"] == today_str()
        assert store.entries(LAYA)["тише"]["added"] == today_str()
        # Миграние должно сохраниться на диск.
        on_disk = json.loads(
            (tmp_path / "knowledge.json").read_text(encoding="utf-8"))
        assert on_disk[CONFIRMED]["стоп"]["added"] == today_str()

    def test_migrate_does_not_touch_existing_added(self, tmp_path):
        data = {CONFIRMED: {"стоп": {"kind": COMMAND, "command": "stop",
                                     "added": "2019-05-05"}}}
        store = KnowledgeStore(_write(tmp_path, data))
        assert store.entries(CONFIRMED)["стоп"]["added"] == "2019-05-05"

    def test_move_preserves_added(self, tmp_path):
        """confirm/demote (_move) переносят запись как есть — дата та же."""
        path = str(tmp_path / "k.json")
        store = KnowledgeStore(path)
        store.record(LAYA, "тише", COMMAND, command="volumedown")
        added = store.entries(LAYA)["тише"]["added"]
        assert store.confirm("тише") is True
        assert store.entries(CONFIRMED)["тише"]["added"] == added
        assert store.demote("тише") is True
        assert store.entries(UNDEFINED)["тише"]["added"] == added

    def test_reload_migrates_entries_added_by_editor(self, tmp_path):
        """Внешний редактор дописал запись без `added` — reload чинит её."""
        path = str(tmp_path / "k.json")
        store = KnowledgeStore(path)
        store.record(LAYA, "раз", COMMAND, command="a")
        data = json.loads(open(path, encoding="utf-8").read())
        data[CONFIRMED]["два"] = {"kind": COMMAND, "command": "b"}
        open(path, "w", encoding="utf-8").write(json.dumps(data))
        future = time.time() + 5
        os.utime(path, (future, future))
        store.reload()
        assert store.entries(CONFIRMED)["два"]["added"] == today_str()

    def test_migration_is_idempotent(self, tmp_path):
        """Второй заход KnowledgeStore по тому же файлу уже ничего не пишет."""
        data = {CONFIRMED: {"стоп": {"kind": COMMAND, "command": "stop"}}}
        path = _write(tmp_path, data)
        KnowledgeStore(path)                                # первая мигрирует
        rolled = time.time() - 30                           # откатим mtime
        os.utime(path, (rolled, rolled))
        KnowledgeStore(path)                                # вторая — no-op
        # Если бы _save дёрнулся ещё раз, mtime прыгнул бы в «now».
        assert abs(os.path.getmtime(path) - rolled) < 2

    def test_synonyms_dont_get_added(self, tmp_path):
        """Synonyms — карта строк «фрагмент → заголовок», поля added нет."""
        path = str(tmp_path / "k.json")
        store = KnowledgeStore(path)
        store.add_synonym("зарядку", "Зарядка")
        data = json.loads(open(path, encoding="utf-8").read())
        assert data["synonyms"]["зарядку"] == "Зарядка"
        assert store.synonyms() == {"зарядку": "Зарядка"}
