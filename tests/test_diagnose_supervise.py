"""Тесты диагностики: супервизор и прогон тестов."""


import os
from lib.diagnose import (MSG_DIRTY, MSG_DONE, MSG_FAIL, MSG_NO_LOGS,
                          MSG_TESTS_FAIL, run_tests)
from lib.diagnose_supervisor import DiagnoseSupervisor


def _write_logs(logs_dir, mtime=1000.0):
    """Создаёт commands_*.log + llm_*.log для чтения коллектором."""
    cmd = os.path.join(logs_dir, "commands_t.log")
    llm = os.path.join(logs_dir, "llm_t.log")
    with open(cmd, "w", encoding="utf-8") as f:
        f.write("10:00 команда выполнена успешно\n10:01 [ERROR] boom\n")
    with open(llm, "w", encoding="utf-8") as f:
        f.write("[USER] найди ошибку\n[ASSISTANT] разбираюсь\n")
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


class TestSupervise:
    """Полный цикл: lock, сбор, попытки, откат."""

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
    """Прогон pytest супервизором."""

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
