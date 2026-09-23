"""Тесты CommandMatcher: подстановки, напоминания, задачи."""


import os
from lib.commands import CommandMatcher


class TestCommandTemplates:
    """Текстовые подстановки и напоминания/задачи."""

    def _write_cfg(self, cfg):
        """Пишет конфиг во временный файл, возвращает путь."""
        import json
        import tempfile
        path = tempfile.mktemp(suffix=".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return path

    def test_get_command_text_substitution_dict(self):
        """{{text}} в dict-шаблоне — слова после команды."""
        path = self._write_cfg({
            "triggers": ["пожалуйста", "алиса"],
            "commands": {
                "task-add": {
                    "linux": "python -m lib.tasks create \"{{text}}\"",
                    "default": "python -m lib.tasks create \"{{text}}\"",
                },
            },
            "match": {"task-add": ["создай задачу"]},
        })
        try:
            matcher = CommandMatcher(path)
            cmd = matcher.get_command(
                "task-add", ("убраться", "у", "кошки"))
            assert cmd == (
                "python -m lib.tasks create \"убраться у кошки\"")
        finally:
            os.unlink(path)

    def test_get_command_text_substitution_plain_string(self):
        """{{text}} работает и в plain-строке (generic commands.json)."""
        path = self._write_cfg({
            "triggers": ["пожалуйста", "алиса"],
            "commands": {
                "calendar-reminder":
                    "python -m lib.reminders \"{{text}}\"",
            },
            "match": {"calendar-reminder": ["напомни"]},
        })
        try:
            matcher = CommandMatcher(path)
            cmd = matcher.get_command(
                "calendar-reminder", ("через", "час", "позвонить"))
            assert cmd == "python -m lib.reminders \"через час позвонить\""
        finally:
            os.unlink(path)

    def test_get_command_text_strips_quotes(self):
        """Кавычки внутри текста вырезаются (не рвут shell-команду)."""
        path = self._write_cfg({
            "triggers": ["алиса"],
            "commands": {
                "task-add": {
                    "default": "python -m lib.tasks create \"{{text}}\"",
                },
            },
            "match": {"task-add": ["создай задачу"]},
        })
        try:
            matcher = CommandMatcher(path)
            cmd = matcher.get_command("task-add", ("купить", '"хлеб"'))
            assert cmd == "python -m lib.tasks create \"купить хлеб\""
        finally:
            os.unlink(path)

    def test_find_command_reminder(self):
        """[Алиса] _напомни_ {через 30 минут} {сходить в магазин}."""
        path = self._write_cfg({
            "triggers": ["пожалуйста", "алиса"],
            "commands": {
                "calendar-reminder": {
                    "default": "python -m lib.reminders \"{{text}}\"",
                },
            },
            "match": {
                "calendar-reminder": [
                    "напомни", "напомни мне", "поставь напоминание",
                ],
            },
        })
        try:
            matcher = CommandMatcher(path)
            assert matcher.find_command([
                "алиса напомни через тридцать минут сходить в магазин",
            ]) == ("calendar-reminder", [
                "через", "тридцать", "минут", "сходить", "в", "магазин",
            ], False)
        finally:
            os.unlink(path)

    def test_find_command_reminder_multiword_template(self):
        """_поставь напоминание_ — двухсловный шаблон, текст после."""
        path = self._write_cfg({
            "triggers": ["пожалуйста", "алиса"],
            "commands": {
                "calendar-reminder": {
                    "default": "python -m lib.reminders \"{{text}}\"",
                },
            },
            "match": {
                "calendar-reminder": [
                    "напомни", "напомни мне", "поставь напоминание",
                ],
            },
        })
        try:
            matcher = CommandMatcher(path)
            assert matcher.find_command([
                "алиса поставь напоминание позвонить маме",
            ]) == ("calendar-reminder", ["позвонить", "маме"], False)
        finally:
            os.unlink(path)

    def test_find_command_task_add(self):
        """[пожалуйста] _создай задачу_ {Убраться у кошки}."""
        path = self._write_cfg({
            "triggers": ["пожалуйста", "алиса"],
            "commands": {
                "task-add": {
                    "default": "python -m lib.tasks create \"{{text}}\"",
                },
            },
            "match": {
                "task-add": ["создай задачу", "добавь задачу"],
            },
        })
        try:
            matcher = CommandMatcher(path)
            assert matcher.find_command([
                "пожалуйста создай задачу убраться у кошки",
            ]) == ("task-add", ["убраться", "у", "кошки"], False)
        finally:
            os.unlink(path)

    def test_execute_task_add_builds_shell_command(self, mocker):
        """execute собирает shell-команду с текстом задачи."""
        mocker.patch("lib.commands.platform.system", return_value="Linux")
        run_mock = mocker.patch("lib.commands.subprocess.run")
        path = self._write_cfg({
            "triggers": ["пожалуйста"],
            "commands": {
                "task-add": {
                    "linux": "python -m lib.tasks create \"{{text}}\"",
                    "default": "python -m lib.tasks create \"{{text}}\"",
                },
            },
            "match": {"task-add": ["создай задачу"]},
        })
        try:
            matcher = CommandMatcher(path)
            assert matcher.execute_by_id(
                "task-add", ("убраться", "у", "кошки")) is True
            run_mock.assert_called_once_with(
                "python -m lib.tasks create \"убраться у кошки\"",
                shell=True, check=True)
        finally:
            os.unlink(path)
