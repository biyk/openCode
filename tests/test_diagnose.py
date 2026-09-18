"""Тесты команды «Анализ/Диагностика» (lib/diagnose.py)."""

import os
import subprocess

from lib.diagnose import (
    MSG_BUSY,
    MSG_DIRTY,
    MSG_DONE,
    MSG_FAIL,
    MSG_NO_LOGS,
    MSG_TESTS_FAIL,
    TRIGGER_PHRASES,
    DiagnoseSupervisor,
    acquire_lock,
    build_prompt,
    git_status_dirty,
    is_stale,
    main,
    release_lock,
    rollback_changes,
    run_tests,
)


def _write_logs(logs_dir, mtime=1000.0):
    """Кладёт commands_*.log + llm_*.log в каталог, возвращает пути."""
    cmd = os.path.join(logs_dir, "commands_t.log")
    llm = os.path.join(logs_dir, "llm_t.log")
    with open(cmd, "w", encoding="utf-8") as f:
        f.write("10:00 алиса сделай громче\n10:01 [ERROR] boom\n")
    with open(llm, "w", encoding="utf-8") as f:
        f.write("[USER] сделай громче\n[ASSISTANT] сделано\n")
    os.utime(cmd, (mtime, mtime))
    os.utime(llm, (mtime, mtime))
    return cmd, llm


class FakeRunner:
    """Фейк OpenCodeCliRunner: сценарий поведения агента."""

    def __init__(self, repo, mode="ok"):
        self.repo = repo
        self.mode = mode
        self.calls = []
        self.workfile = os.path.join(repo, "WORKING.MD")

    def _touch_workfile(self):
        with open(self.workfile, "w", encoding="utf-8") as f:
            f.write("статус: работаю")

    def run(self, prompt, abort_event=None, raw=False,
            verbose=None, timeout=None):
        self.calls.append({
            "raw": raw, "timeout": timeout,
            "prompt": prompt,
        })
        if self.mode == "ok":
            # Агент по протоколу: создал, отметил, удалил.
            self._touch_workfile()
            with open(self.workfile, "w", encoding="utf-8") as f:
                f.write("статус: готово")
            os.unlink(self.workfile)
            return "исправлено: всё ок"
        if self.mode == "hang":
            # Агент создал файл, но завис: ждём abort от вотчдога.
            self._touch_workfile()
            if abort_event is not None:
                abort_event.wait(timeout=5)
            return None
        if self.mode == "fail":
            return None
        raise AssertionError(f"unknown mode {self.mode}")


def _supervisor(tmp_path, runner, **kwargs):
    logs_dir = os.path.join(str(tmp_path), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    said = []
    kwargs.setdefault("poll_interval", 0.01)
    sup = DiagnoseSupervisor(
        runner=runner, repo_root=str(tmp_path), logs_dir=logs_dir,
        on_say=said.append, **kwargs)
    return sup, said


class TestBuildPrompt:
    """Промпт: путь лога, хвост, чат, протокол WORKING.MD."""

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
    """git status --porcelain → грязный/чистый/ошибка."""

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
    """Чистая функция простоя прогресса."""

    def test_stale(self):
        assert is_stale(100.0, 800.0, 600.0) is True

    def test_fresh(self):
        assert is_stale(700.0, 800.0, 600.0) is False


class TestLock:
    """Lock-файл: повторный запуск блокируется, мёртвый — нет."""

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
    """Откат: git checkout + удаление WORKING.MD."""

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


class TestSupervise:
    """Цикл супервизора: успех/грязь/вис/провал."""

    def test_dirty_repo_no_launch(self, tmp_path, mocker):
        runner = FakeRunner(str(tmp_path))
        sup, said = _supervisor(tmp_path, runner)
        mocker.patch("lib.diagnose.git_status_dirty", return_value=True)
        assert sup.supervise("") == 4
        assert runner.calls == []
        assert any(MSG_DIRTY in s for s in said)

    def test_no_logs(self, tmp_path, mocker):
        runner = FakeRunner(str(tmp_path))
        sup, said = _supervisor(tmp_path, runner)
        mocker.patch("lib.diagnose.git_status_dirty", return_value=False)
        assert sup.supervise("") == 4
        assert any(MSG_NO_LOGS in s for s in said)

    def test_success(self, tmp_path, mocker):
        runner = FakeRunner(str(tmp_path), mode="ok")
        sup, said = _supervisor(tmp_path, runner)
        mocker.patch("lib.diagnose.git_status_dirty", return_value=False)
        mocker.patch("lib.diagnose.run_tests",
                     return_value=(True, "12 passed"))
        _write_logs(os.path.join(str(tmp_path), "logs"))
        assert sup.supervise("громкость") == 0
        assert len(runner.calls) == 1
        assert runner.calls[0]["raw"] is True
        assert any(MSG_DONE in s for s in said)

    def test_tests_fail_rolls_back_and_retries(self, tmp_path, mocker):
        """WORKING.MD пропал, но тесты красные — откат + хвост в промпте."""
        runner = FakeRunner(str(tmp_path), mode="ok")
        sup, said = _supervisor(tmp_path, runner, max_attempts=2)
        mocker.patch("lib.diagnose.git_status_dirty", return_value=False)
        mocker.patch("lib.diagnose.run_tests",
                     return_value=(False, "FAILED test_x - boom"))
        rolled = []
        mocker.patch("lib.diagnose.rollback_changes",
                     side_effect=lambda *a: rolled.append(1))
        _write_logs(os.path.join(str(tmp_path), "logs"))
        assert sup.supervise("") == 1
        assert len(runner.calls) == 2
        assert len(rolled) == 1
        assert any(MSG_TESTS_FAIL in s for s in said)
        assert "FAILED test_x" not in runner.calls[0]["prompt"]
        assert "FAILED test_x" in runner.calls[1]["prompt"]

    def test_stale_retries_then_fails(self, tmp_path, mocker):
        runner = FakeRunner(str(tmp_path), mode="hang")
        sup, said = _supervisor(
            tmp_path, runner, stale_limit=0.0, poll_interval=0.01,
            max_attempts=2)
        mocker.patch("lib.diagnose.git_status_dirty", return_value=False)
        mocker.patch("lib.diagnose.run_tests",
                     return_value=(True, ""))
        rolled = []
        mocker.patch("lib.diagnose.rollback_changes",
                     side_effect=lambda *a: rolled.append(1))
        _write_logs(os.path.join(str(tmp_path), "logs"))
        assert sup.supervise("") == 1
        assert len(runner.calls) == 2
        assert len(rolled) == 1
        assert any(MSG_FAIL in s for s in said)

    def test_fail_rolls_back(self, tmp_path, mocker):
        runner = FakeRunner(str(tmp_path), mode="fail")
        sup, said = _supervisor(tmp_path, runner, max_attempts=2)
        mocker.patch("lib.diagnose.git_status_dirty", return_value=False)
        mocker.patch("lib.diagnose.run_tests",
                     return_value=(True, ""))
        rolled = []
        mocker.patch("lib.diagnose.rollback_changes",
                     side_effect=lambda *a: rolled.append(1))
        _write_logs(os.path.join(str(tmp_path), "logs"))
        assert sup.supervise("") == 1
        assert len(runner.calls) == 2
        assert len(rolled) == 1


class TestRunTests:
    """Хелпер прогона pytest: коды, хвост, падение запуска."""

    def test_passed(self, mocker):
        proc = mocker.MagicMock()
        proc.returncode = 0
        proc.stdout = "12 passed\n"
        proc.stderr = ""
        mocker.patch("lib.diagnose.subprocess.run", return_value=proc)
        passed, tail = run_tests("/repo")
        assert passed is True
        assert "12 passed" in tail

    def test_failed(self, mocker):
        proc = mocker.MagicMock()
        proc.returncode = 1
        proc.stdout = "FAILED test_x\n1 failed\n"
        proc.stderr = ""
        mocker.patch("lib.diagnose.subprocess.run", return_value=proc)
        passed, tail = run_tests("/repo")
        assert passed is False
        assert "FAILED test_x" in tail

    def test_launch_error(self, mocker):
        mocker.patch("lib.diagnose.subprocess.run",
                     side_effect=OSError("no python"))
        passed, tail = run_tests("/repo")
        assert passed is False
        assert tail != ""


class TestMain:
    """CLI: launch спавнит detached, usage-коды."""

    def test_usage(self, capsys):
        assert main([]) == 2
        assert main(["bogus"]) == 2
        assert "usage" in capsys.readouterr().out

    def test_launch_detached(self, tmp_path, mocker):
        popen = mocker.patch("lib.diagnose.subprocess.Popen")
        assert main.__module__ == "lib.diagnose"
        import lib.diagnose as diag
        real_repo = diag.REPO_ROOT
        diag.REPO_ROOT = str(tmp_path)
        try:
            code = diag.main(["launch", "громкость"])
        finally:
            diag.REPO_ROOT = real_repo
        assert code == 0
        assert popen.call_count == 1
        argv = popen.call_args.args[0]
        assert argv[1:4] == ["-m", "lib.diagnose", "run"]
        assert argv[4] == "громкость"
        kwargs = popen.call_args.kwargs
        assert kwargs["stdout"] is not None
        assert kwargs["stdin"] is subprocess.DEVNULL

    def test_busy_run(self, tmp_path, mocker, capsys):
        import lib.diagnose as diag
        real_repo = diag.REPO_ROOT
        diag.REPO_ROOT = str(tmp_path)
        mocker.patch("lib.diagnose._pid_alive", return_value=True)
        voiced = []
        mocker.patch("lib.diagnose.TextToSpeech")
        mocker.patch.object(
            diag.TranscriptionOutput, "print_info",
            side_effect=lambda *a: voiced.append(a))
        try:
            assert acquire_lock(str(tmp_path)) is True
            code = diag.main(["run", ""])
        finally:
            diag.REPO_ROOT = real_repo
            release_lock(str(tmp_path))
        assert code == 4
        assert any(MSG_BUSY in str(a) for a in voiced)


class TestTriggers:
    """Триггеры команды есть, в find_command — без конфликтов."""

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
        from lib.commands import CommandMatcher
        matcher = CommandMatcher(path)
        assert matcher.find_command(["алиса анализ"]) == (
            "diagnose", [], False)
        assert matcher.find_command(["алиса проверь логи"]) == (
            "diagnose", [], False)
        assert matcher.find_command(["пожалуйста выключи"]) == (
            "stop", [], False)
