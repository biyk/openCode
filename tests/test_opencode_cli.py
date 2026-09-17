"""Тесты фолбэк-раннера console opencode (lib/opencode_cli.py)."""

import threading
from unittest.mock import MagicMock

from lib.opencode_cli import OpenCodeCliRunner


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
    def test_returns_path_when_opencode_on_path(self, mocker):
        mocker.patch(
            "lib.opencode_cli.shutil.which", return_value=r"C:\x\opencode.exe")
        from lib.opencode_cli import _find_opencode_exe
        assert _find_opencode_exe() == r"C:\x\opencode.exe"

    def test_returns_none_when_not_found(self, mocker):
        mocker.patch("lib.opencode_cli.shutil.which", return_value=None)
        mocker.patch("lib.opencode_cli.os.path.isfile", return_value=False)
        mocker.patch("lib.opencode_cli.os.environ.get", side_effect=lambda *a: "")
        from lib.opencode_cli import _find_opencode_exe
        assert _find_opencode_exe() is None


class TestRunner:
    def _runner(self, mocker, **kwargs):
        mocker.patch("lib.opencode_cli._find_opencode_exe", return_value=r"C:\x\opencode.exe")
        return OpenCodeCliRunner(cli_dir=r"C:\cli", output=mocker.MagicMock(), **kwargs)

    def test_run_empty_text_returns_none(self, mocker):
        runner = self._runner(mocker)
        assert runner.run("   ") is None
        runner._output.print_error.assert_not_called()

    def test_run_missing_cli_dir_returns_none(self, mocker):
        mocker.patch("lib.opencode_cli.os.path.isdir", return_value=False)
        runner = self._runner(mocker)
        assert runner.run("сделай громче") is None

    def test_run_success_captures_stdout(self, mocker):
        proc = FakeProc(["привет", "АНСИ \x1b[31mкрасиво\x1b[0m"])
        popen = mocker.patch("lib.opencode_cli.subprocess.Popen", return_value=proc)
        mocker.patch("lib.opencode_cli.os.path.isdir", return_value=True)
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
            "lib.opencode_cli.subprocess.Popen", return_value=proc)
        mocker.patch("lib.opencode_cli.os.path.isdir", return_value=True)
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
            "lib.opencode_cli.subprocess.Popen", return_value=proc)
        mocker.patch("lib.opencode_cli.os.path.isdir", return_value=True)
        runner = self._runner(mocker, timeout=0.01)
        result = runner.run("команда")
        assert result is None
        assert prod.called

    def test_run_file_not_found(self, mocker):
        mocker.patch(
            "lib.opencode_cli.subprocess.Popen",
            side_effect=FileNotFoundError("no opencode"))
        mocker.patch("lib.opencode_cli.os.path.isdir", return_value=True)
        runner = self._runner(mocker)
        assert runner.run("команда") is None

    def test_run_reports_empty_output(self, mocker):
        proc = FakeProc([], returncode=1)
        mocker.patch("lib.opencode_cli.subprocess.Popen", return_value=proc)
        mocker.patch("lib.opencode_cli.os.path.isdir", return_value=True)
        runner = self._runner(mocker)
        assert runner.run("команда") is None

    def test_clean_strips_ansi_and_empty_lines(self):
        runner = self._runner(MagicMock())
        # _runner нужен только ради объекта; вызываем _clean напрямую
        result = runner._clean("> \nthinking...\nпривет\n\nкрасиво\x1b[0m\n")
        assert "привет" in result
        assert "красиво" in result
        assert ">" not in result

    def test_clean_strips_agent_noise_blocks(self):
        """Мёртвые инструменты и JSON-параметры агента не попадают в итог."""
        runner = self._runner(MagicMock())
        sample = (
            "> build · auto/tools\n"
            "✗ grep_search {\"includePattern\":\"**/*\"} failed\n"
            "Error: No tool named \"grep_search\" is currently available.\n"
            "> build · auto/tools\n"
            "Error: Invalid arguments for tool \"read\":\n"
            "- path: Missing key\n"
            "Arguments provided:\n"
            "{\n"
            "  \"filePath\": \"C:\\\\x\\\\AGENTS.md\",\n"
            "  \"startLine\": \"1\"\n"
            "}\n"
            "<system-reminder>\nRead the AGENTS.md file.\n</system-reminder>\n"
            "<parameter=maxResults>\n200\n</parameter>\n"
            "<parameter=query>\n**/*.ps1\n</parameter>\n"
            "</function>\n"
            "> build · auto/tools\n"
            "$ cd C:\\Users\\b5\\Desktop\\voice; python -c \"x\"\n"
            "Задача не найдена, ничего не выполнено.\n"
        )
        result = runner._clean(sample)
        assert "grep_search" not in result
        assert "No tool named" not in result
        assert "filePath" not in result
        assert "Read the AGENTS.md" not in result
        assert "**/*.ps1" not in result
        assert "> build" not in result
        assert "$ cd" not in result
        assert "Задача не найдена" in result

    def test_clean_success_keeps_result_tail(self):
        """Итоговая фраза агента после команд сохраняется."""
        runner = self._runner(MagicMock())
        sample = (
            "$ cd C:\\x; python -c \"print(1)\"\n"
            "Задача выполнена: накормить хомяка\n"
        )
        result = runner._clean(sample)
        assert result == "Задача выполнена: накормить хомяка"

    def test_clean_strips_tool_call_markup_text(self):
        """Tool-call разметка агента, выведенная текстом, не попадает в итог."""
        runner = self._runner(MagicMock())
        sample = (
            "Я выполняю скилл task-complete.\n"
            "<\uff5ctool\uff5c calls>\n"
            "<\uff5c invoke name=\"shell\">\n"
            "<\uff5c parameter name=\"command\" string=\"true\">"
            "cd C:\\x; python -m lib.tasks complete --b64:xxx"
            "</\uff5c parameter>\n"
            "<\uff5c parameter name=\"workdir\" string=\"true\">C:\\x</\uff5c"
            " parameter>\n"
            "</\uff5c invoke>\n"
            "</\uff5c calls>\n"
            "title: починить лампочку в ванной\n"
            "result: {\"matched\": []}\n"
        )
        result = runner._clean(sample)
        assert "tool" not in result
        assert "invoke" not in result
        assert "parameter" not in result
        assert "calls" not in result
        assert "Я выполняю скилл" in result
        assert "title:" in result
        assert "result:" in result

    def test_clean_strips_ascii_tool_call_markup(self):
        """ASCII-вариант разметки <|tool| ...> тоже отбрасывается."""
        runner = self._runner(MagicMock())
        sample = (
            "<|tool| calls>\n"
            "<|invoke name=\"shell\">\n"
            "</|calls>\n"
            "итог\n"
        )
        result = runner._clean(sample)
        assert "invoke" not in result
        assert "calls" not in result
        assert result == "итог"
