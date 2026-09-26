"""Тесты диагностики: промпт, git, lock, откат."""


import os
from lib.diagnose import TRIGGER_PHRASES, acquire_lock, build_prompt
from lib.diagnose import git_status_dirty, is_stale, release_lock
from lib.diagnose import rollback_changes


class TestBuildPrompt:
    """Промпт: путь лога, хвост, чат, протокол."""

    def test_prompt_content(self):
        prompt = build_prompt(
            "logs/commands_x.log",
            ["10:01 [ERROR] boom"],
            [{"role": "user", "content": "сделай громче"}],
            "громкость")
        assert "logs/commands_x.log" in prompt
        assert "[ERROR] boom" in prompt
        assert "сделай громче" in prompt
        assert "WORKING.MD" in prompt
        assert "УДАЛИ" in prompt
        assert "громкость" in prompt

    def test_prompt_empty_focus(self):
        prompt = build_prompt("p", [], [], "")
        assert "Фокус: всё" in prompt

    def test_prompt_extra(self):
        """Хвост прошлого запуска прикладывается к промпту."""
        prompt = build_prompt("p", [], [], "", "FAILED test_x")
        assert "Результат прошлого запуска:" in prompt
        assert "FAILED test_x" in prompt

    def test_prompt_mentions_tests(self):
        """Агент знает: после WORKING.MD — тесты, провал — возврат."""
        prompt = build_prompt("p", [], [], "")
        assert "pytest" in prompt
        assert "WORKING.MD" in prompt


class TestGitDirty:
    """Грязный git-статус."""

    def test_dirty(self, mocker):
        proc = mocker.MagicMock()
        proc.returncode = 0
        proc.stdout = " M lib/a.py\n"
        mocker.patch(
            "lib.diagnose.subprocess.run", return_value=proc)
        assert git_status_dirty("/repo") is True

    def test_clean(self, mocker):
        proc = mocker.MagicMock()
        proc.returncode = 0
        proc.stdout = "\n"
        mocker.patch(
            "lib.diagnose.subprocess.run", return_value=proc)
        assert git_status_dirty("/repo") is False

    def test_git_error_is_dirty(self, mocker):
        mocker.patch("lib.diagnose.subprocess.run",
                     side_effect=OSError("no git"))
        assert git_status_dirty("/repo") is True


class TestIsStale:
    """Простой прогресса дольше лимита."""

    def test_stale(self):
        assert is_stale(100.0, 800.0, 600.0) is True

    def test_fresh(self):
        assert is_stale(700.0, 800.0, 600.0) is False


class TestLock:
    """Lock-файл диагностики."""

    def test_acquire_release(self, tmp_path):
        repo = str(tmp_path)
        assert acquire_lock(repo) is True
        assert os.path.exists(os.path.join(repo, "logs", "diagnose.lock"))
        release_lock(repo)
        assert not os.path.exists(
            os.path.join(repo, "logs", "diagnose.lock"))

    def test_busy_when_alive(self, tmp_path, mocker):
        repo = str(tmp_path)
        assert acquire_lock(repo) is True
        mocker.patch("lib.diagnose._pid_alive", return_value=True)
        assert acquire_lock(repo) is False
        release_lock(repo)

    def test_takeover_when_dead(self, tmp_path, mocker):
        repo = str(tmp_path)
        assert acquire_lock(repo) is True
        mocker.patch("lib.diagnose._pid_alive", return_value=False)
        assert acquire_lock(repo) is True
        release_lock(repo)


class TestRollback:
    """Откат изменений."""

    def test_rollback(self, tmp_path, mocker):
        repo = str(tmp_path)
        run_mock = mocker.patch("lib.diagnose.subprocess.run")
        work = os.path.join(repo, "WORKING.MD")
        with open(work, "w", encoding="utf-8") as f:
            f.write("x")
        rollback_changes(repo)
        run_mock.assert_called_once()
        assert run_mock.call_args.args[0] == ["git", "checkout", "--", "."]
        assert not os.path.exists(work)


class TestTriggers:
    """Триггеры команды в find_command."""

    def test_trigger_phrases(self):
        assert "анализ" in TRIGGER_PHRASES
        assert "диагностика" in TRIGGER_PHRASES
        assert "проверь логи" in TRIGGER_PHRASES

    def test_find_command_diagnose(self, tmp_path):
        import json
        cfg = {
            "triggers": ["пожалуйста", "алиса"],
            "commands": {"diagnose": "python -m lib.diagnose",
                         "stop": "echo stop"},
            "match": {
                "diagnose": list(TRIGGER_PHRASES),
                "stop": ["стоп", "выключи"],
            },
        }
        path = str(tmp_path / "cmd.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        from lib.voice_cmd.commands import CommandMatcher
        matcher = CommandMatcher(path)
        assert matcher.find_command(["алиса анализ"]) == (
            "diagnose", [], False)
        assert matcher.find_command(["алиса проверь логи"]) == (
            "diagnose", [], False)
        assert matcher.find_command(["пожалуйста выключи"]) == (
            "stop", [], False)
