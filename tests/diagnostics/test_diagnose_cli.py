"""Тесты диагностики: CLI launch/run."""


import subprocess
from lib.diagnose import (MSG_BUSY, acquire_lock, release_lock)
from lib.diagnostics.diagnose_cli import main


class TestMain:
    """CLI: launch detached, usage-коды, busy."""

    def test_usage(self, capsys):
        assert main([]) == 2
        assert main(["bogus"]) == 2
        assert "usage" in capsys.readouterr().out

    def test_launch_detached(self, tmp_path, mocker):
        popen = mocker.patch("lib.diagnostics.diagnose_cli.subprocess.Popen")
        assert main.__module__ == "lib.diagnostics.diagnose_cli"
        import lib.diagnose as diag
        real_repo = diag.REPO_ROOT
        diag.REPO_ROOT = str(tmp_path)
        try:
            code = main(["launch", "громкость"])
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
        mocker.patch("lib.diagnostics.diagnose_supervisor.TextToSpeech")
        mocker.patch(
            "lib.diagnostics.diagnose_supervisor.TranscriptionOutput.print_info",
            side_effect=lambda *a: voiced.append(a))
        try:
            assert acquire_lock(str(tmp_path)) is True
            code = main(["run", ""])
        finally:
            diag.REPO_ROOT = real_repo
            release_lock(str(tmp_path))
        assert code == 4
        assert any(MSG_BUSY in str(a) for a in voiced)
