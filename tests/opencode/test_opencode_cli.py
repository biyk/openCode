"""Тесты console opencode: поиск exe, запуск."""


import threading
from unittest.mock import MagicMock
from lib.opencode.opencode_cli import OpenCodeCliRunner


class FakeProc:
    """Имитация подпроцесса с конечным stdout."""

    def __init__(self, lines, returncode=0):
        self._lines = [line + "\n" for line in lines] + [""]
        self.poll_result = None
        self.returncode_value = returncode
        self.killed = False
        self.stdout = self

    def readline(self):
        return self._lines.pop(0)

    def poll(self):
        return self.poll_result

    def kill(self):
        self.killed = True

    def wait(self, timeout=5):
        self.poll_result = self.returncode_value
        return self.returncode_value


class TestFindExe:
    """Поиск исполняемого файла opencode."""

    def test_returns_path_when_opencode_on_path(self, mocker):
        mocker.patch(
            "lib.opencode.opencode_cli.shutil.which", return_value=r"C:\x\opencode.exe")
        from lib.opencode.opencode_cli import _find_opencode_exe
        assert _find_opencode_exe() == r"C:\x\opencode.exe"

    def test_returns_none_when_not_found(self, mocker):
        mocker.patch("lib.opencode.opencode_cli.shutil.which", return_value=None)
        mocker.patch("lib.opencode.opencode_cli.os.path.isfile", return_value=False)
        mocker.patch("lib.opencode.opencode_cli.os.environ.get", side_effect=lambda *a: "")
        from lib.opencode.opencode_cli import _find_opencode_exe
        assert _find_opencode_exe() is None


class TestRunnerStart:
    """Валидация, успешный запуск, abort, таймаут."""

    def _runner(self, mocker, **kwargs):
        mocker.patch(
            "lib.opencode.opencode_cli._find_opencode_exe",
            return_value=r"C:\x\opencode.exe")
        return OpenCodeCliRunner(cli_dir=r"C:\cli", output=mocker.MagicMock(), **kwargs)

    def test_run_empty_text_returns_none(self, mocker):
        runner = self._runner(mocker)
        assert runner.run("   ") is None
        runner._output.print_error.assert_not_called()

    def test_run_missing_cli_dir_returns_none(self, mocker):
        mocker.patch("lib.opencode.opencode_cli.os.path.isdir", return_value=False)
        runner = self._runner(mocker)
        assert runner.run("сделай громче") is None

    def test_run_success_captures_stdout(self, mocker):
        proc = FakeProc(["привет", "АНСИ \x1b[31mкрасиво\x1b[0m"])
        popen = mocker.patch("lib.opencode.opencode_cli.subprocess.Popen", return_value=proc)
        mocker.patch("lib.opencode.opencode_cli.os.path.isdir", return_value=True)
        runner = self._runner(mocker)
        result = runner.run("сделай громче")
        assert result == "привет\nАНСИ красиво"
        cmd = popen.call_args[0][0]
        assert cmd[0] == r"C:\x\opencode.exe"
        assert cmd[1] == "run"
        assert "--model" in cmd
        assert "omnirouter/auto/tools" in cmd
        assert "сделай громче" in cmd[-1]
        assert popen.call_args[1]["cwd"] == r"C:\cli"

    def test_run_kills_on_abort(self, mocker):
        proc = FakeProc(["частичный"])
        proc.poll_result = None  # держим процесс живым

        prod = mocker.patch(
            "lib.opencode.opencode_cli.subprocess.Popen", return_value=proc)
        mocker.patch("lib.opencode.opencode_cli.os.path.isdir", return_value=True)
        abort = threading.Event()
        runner = self._runner(mocker)
        runner._timeout = 30.0
        # Первый abort-чек прерывает цикл
        original_is_set = abort.is_set
        abort.is_set = MagicMock(side_effect=[False, True])
        result = runner.run("сделай громче", abort_event=abort)
        abort.is_set = original_is_set
        assert result is None
        assert prod.called
        assert proc.killed

    def test_run_timeout_returns_none(self, mocker):
        proc = FakeProc([""])  # молчаливый процесс, не завершается

        def _poll(*a, **k):
            return None

        proc.poll = _poll
        prod = mocker.patch(
            "lib.opencode.opencode_cli.subprocess.Popen", return_value=proc)
        mocker.patch("lib.opencode.opencode_cli.os.path.isdir", return_value=True)
        runner = self._runner(mocker, timeout=0.01)
        result = runner.run("команда")
        assert result is None
        assert prod.called

    def test_run_file_not_found(self, mocker):
        mocker.patch(
            "lib.opencode.opencode_cli.subprocess.Popen",
            side_effect=FileNotFoundError("no opencode"))
        mocker.patch("lib.opencode.opencode_cli.os.path.isdir", return_value=True)
        runner = self._runner(mocker)
        assert runner.run("команда") is None
