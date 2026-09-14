"""Тесты базы соответствий «коверканье → команда» (П6.0)."""

import json
import os
import tempfile

from lib.aliases import AliasStore, normalize_core


def _write_aliases(data):
    """Пишет aliases.json во временный файл, возвращает путь."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def _sample():
    return {
        "aliases": {
            "включи и ютюб": {
                "command": "openyoutube", "hits": 2, "confirmed": True,
            },
        },
        "pending": {
            "паузы": {
                "command": "playpause", "hits": 1, "confirmed": False,
            },
        },
    }


class TestNormalizeCore:
    """Нормализация фраз."""

    def test_lower_and_spaces(self):
        assert normalize_core("  Алиса  ВКЛЮЧИ   ютуб ") == "алиса включи ютуб"

    def test_yo_to_e(self):
        assert normalize_core("ютюб") == "ютюб"
        assert normalize_core("ЁЖИК") == "ежик"


class TestAliasStoreLoading:
    """Загрузка и состояние."""

    def test_missing_file_disabled(self, tmp_path):
        store = AliasStore(str(tmp_path / "none.json"))
        assert store.enabled is False
        assert store.resolve("что-то") is None

    def test_path_for_commands_file(self):
        assert AliasStore.path_for_commands_file(
            os.path.join("x", "targets", "HOST", "commands.json")
        ) == os.path.join("x", "targets", "HOST", "aliases.json")

    def test_resolve_confirmed(self):
        path = _write_aliases(_sample())
        try:
            store = AliasStore(path)
            assert store.enabled is True
            assert store.resolve("Включи и ЮТЮБ") == "openyoutube"
        finally:
            os.unlink(path)

    def test_resolve_ignores_pending(self):
        path = _write_aliases(_sample())
        try:
            store = AliasStore(path)
            assert store.resolve("паузы") is None
        finally:
            os.unlink(path)

    def test_resolve_unknown_none(self):
        path = _write_aliases(_sample())
        try:
            store = AliasStore(path)
            assert store.resolve("абракадабра") is None
        finally:
            os.unlink(path)

    def test_aliases_list_only_confirmed(self):
        path = _write_aliases(_sample())
        try:
            store = AliasStore(path)
            assert list(store.aliases_list()) == ["включи и ютюб"]
            assert list(store.pending_list()) == ["паузы"]
        finally:
            os.unlink(path)


class TestAliasStoreMutations:
    """add/confirm/forget/bump."""

    def test_add_confirmed(self, tmp_path):
        path = str(tmp_path / "a.json")
        store = AliasStore(path)
        assert store.add("Громче!", "volumeup") is True
        assert store.resolve("громче!") == "volumeup"
        assert store.enabled is True

    def test_add_rejects_empty(self, tmp_path):
        store = AliasStore(str(tmp_path / "a.json"))
        assert store.add("", "volumeup") is False
        assert store.add("громче", "") is False
        assert store.add("   ", "  ") is False

    def test_add_pending(self, tmp_path):
        store = AliasStore(str(tmp_path / "a.json"))
        assert store.add("паузы", "playpause", confirmed=False) is True
        assert store.resolve("паузы") is None
        assert list(store.pending_list()) == ["паузы"]

    def test_add_pending_skips_existing_alias(self, tmp_path):
        store = AliasStore(str(tmp_path / "a.json"))
        store.add("паузы", "playpause", confirmed=True)
        store.add("паузы", "stop", confirmed=False)
        assert store.resolve("паузы") == "playpause"
        assert store.pending_list() == {}

    def test_confirm_moves_pending(self, tmp_path):
        store = AliasStore(str(tmp_path / "a.json"))
        store.add("паузы", "playpause", confirmed=False)
        assert store.confirm("Паузы") == "playpause"
        assert store.resolve("паузы") == "playpause"
        assert store.pending_list() == {}

    def test_confirm_missing_returns_none(self, tmp_path):
        store = AliasStore(str(tmp_path / "a.json"))
        assert store.confirm("нет такого") is None

    def test_forget_removes(self, tmp_path):
        store = AliasStore(str(tmp_path / "a.json"))
        store.add("паузы", "playpause", confirmed=True)
        store.add("громче", "volumeup", confirmed=False)
        assert store.forget("Паузы") is True
        assert store.resolve("паузы") is None
        assert store.forget("Громче") is True
        assert store.forget("нет такого") is False

    def test_bump_counts_hits(self, tmp_path):
        store = AliasStore(str(tmp_path / "a.json"))
        store.add("паузы", "playpause", confirmed=True)
        store.bump("паузы")
        store.bump("паузы")
        assert store.aliases_list()["паузы"]["hits"] == 2

    def test_bump_unknown_noop(self, tmp_path):
        store = AliasStore(str(tmp_path / "a.json"))
        store.bump("нет такого")

    def test_persisted_to_disk(self, tmp_path):
        path = str(tmp_path / "a.json")
        store = AliasStore(path)
        store.add("паузы", "playpause", confirmed=True)
        data = json.load(open(path, encoding="utf-8"))
        assert data["aliases"]["паузы"]["command"] == "playpause"
        assert data["aliases"]["паузы"]["confirmed"] is True

    def test_reload_picks_up_changes(self, tmp_path):
        import time
        path = str(tmp_path / "a.json")
        store = AliasStore(path)
        store.add("паузы", "playpause", confirmed=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"aliases": {}, "pending": {}}, f)
        future = time.time() + 5
        os.utime(path, (future, future))
        assert store.resolve("паузы") is None

    def test_invalid_file_tolerated(self, tmp_path):
        path = str(tmp_path / "a.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{битый")
        store = AliasStore(path)
        assert store.enabled is False
        assert store.resolve("паузы") is None
