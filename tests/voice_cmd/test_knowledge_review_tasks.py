"""Тесты подсказки task-complete: названия задач из real_life_tasks.

Чтение Google Таблицы дорогое, поэтому список кэшируется и отдаётся доске
отдельным эндпоинтом /api/tasks (страница тянет его только для строк с
командой task-complete).
"""

import json
import sys
import threading
import types
import urllib.request

import pytest

from lib.voice_cmd import knowledge_review_board as kb_mod
from lib.voice_cmd.knowledge import KnowledgeStore
from lib.voice_cmd.knowledge_review_board import commands_lists, \
    sheet_task_titles
from lib.voice_cmd.knowledge_review_server import make_server


@pytest.fixture
def cfile(tmp_path):
    """Временный commands.json с id task-complete (как в targets/)."""
    data = {"commands": {"task-complete": "cmd"},
            "descriptions": {"task-complete": "отметить задачу выполненной"},
            "decision": {"enabled": False}}
    path = tmp_path / "commands.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _fake_sheet(monkeypatch, rows=None):
    """Сброс кэша + подмена real_life_sheet (rows=None → модуля нет)."""
    monkeypatch.setattr(kb_mod, "_tasks_cache", (0.0, []))
    if rows is None:
        monkeypatch.setitem(sys.modules, "lib.taskflow.real_life_sheet", None)
        return
    sheet = types.SimpleNamespace(read_all_tasks=lambda: rows)
    monkeypatch.setitem(sys.modules, "lib.taskflow.real_life_sheet",
                        types.SimpleNamespace(RealLifeSheet=lambda: sheet))


def _http(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}",
                                timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


class TestSheetTasks:
    def test_empty_on_import_failure(self, monkeypatch):
        # Без googleapiclient/OAuth — пустой список, не падение.
        _fake_sheet(monkeypatch)
        assert sheet_task_titles() == []

    def test_uses_cache(self, monkeypatch):
        monkeypatch.setattr(kb_mod, "_tasks_cache",
                            (kb_mod.time.time(), ["Пробежка"]))
        assert sheet_task_titles() == ["Пробежка"]

    def test_dedupes_titles(self, monkeypatch):
        # Повторы названия в таблице (повторяющиеся задачи) → один пункт.
        _fake_sheet(monkeypatch, [{"task_title": "Прогулка"},
                                  {"task_title": " Прогулка "},
                                  {"task_title": ""},
                                  {"task_title": "Турник"}])
        assert sheet_task_titles() == ["Прогулка", "Турник"]

    def test_hint_matches_configured_command(self, cfile):
        """Подсказка привязана к id из commands.json — он должен присутствовать."""
        ids, descriptions = commands_lists(cfile)
        assert ids == ["task-complete"]
        assert "отметить" in descriptions["task-complete"]


class TestTasksHttpApi:
    def test_tasks_endpoint_lists_sheet_titles(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.voice_cmd.knowledge_review_server"
                            ".sheet_task_titles", lambda: ["Пробежка"])
        store = KnowledgeStore(str(tmp_path / "knowledge.json"))
        httpd = make_server(store, str(tmp_path / "commands.json"),
                            {"port": 0}, 0)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            assert _http(port, "/api/tasks") == {"tasks": ["Пробежка"]}
        finally:
            httpd.shutdown()
            httpd.server_close()
