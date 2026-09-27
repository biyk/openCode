"""Тесты free-text-команд доски (селект «ключ» из префиксов фразы).

free_text_commands отдаёт id команд с {{text}} — только им UI показывает
селект накопительных префиксов фразы; снимок доски несёт их в поле freeText.
"""

import json

from lib.voice_cmd.knowledge import KnowledgeStore
from lib.voice_cmd.knowledge_review_board import (
    board_snapshot, free_text_commands,
)


def _commands(tmp_path, data):
    path = tmp_path / "commands.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_free_text_commands_only_text_ones(tmp_path):
    # В список попадают только команды, чей шаблон содержит {{text}}.
    cfile = _commands(tmp_path, {
        "commands": {"task-add": 'python -m lib.tasks create "{{text}}"',
                     "volumedown": {"windows": "cmd"},
                     "stop": "python -m lib.x"},
        "match": {}, "decision": {"enabled": False}})
    assert free_text_commands(cfile) == ["task-add"]


def test_free_text_commands_reads_platform_dict_and_str(tmp_path):
    # Понимает и строку-команду, и словарь платформ.
    cfile = _commands(tmp_path, {
        "commands": {"taskstart": "python -m lib.task_start \"{{text}}\"",
                     "calendar-reminder": {"linux": "x {{text}}",
                                           "default": "y {{text}}"}},
        "match": {}, "decision": {"enabled": False}})
    assert free_text_commands(cfile) == ["calendar-reminder", "taskstart"]


def test_board_snapshot_includes_free_text(tmp_path):
    cfile = _commands(tmp_path, {
        "commands": {"task-add": 'python -m lib.tasks "{{text}}"'},
        "match": {"task-add": ["добавь задачу"]},
        "decision": {"enabled": False}})
    store = KnowledgeStore(str(tmp_path / "knowledge.json"))
    snap = board_snapshot(store, cfile, {"port": 8765})
    assert snap["freeText"] == ["task-add"]
