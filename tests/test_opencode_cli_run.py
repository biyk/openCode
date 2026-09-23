"""Тесты console opencode: raw/verbose, дамп при таймауте."""


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


class TestRunnerRun:
    """Режимы запуска и потоковый вывод."""

    def _runner(self, mocker, **kwargs):
        mocker.patch("lib.opencode_cli._find_opencode_exe", return_value=r"C:\x\opencode.exe")
        return OpenCodeCliRunner(cli_dir=r"C:\cli", output=mocker.MagicMock(), **kwargs)

    def test_run_raw_runs_from_repo_root(self, mocker):
        """dev-режим: cwd — корень проекта, текст без BASE_PROMPT-обёртки."""
        from lib.opencode_cli import REPO_ROOT
        proc = FakeProc(["Ответ"])
        popen = mocker.patch(
            "lib.opencode_cli.subprocess.Popen", return_value=proc)
        mocker.patch("lib.opencode_cli.os.path.isdir", return_value=True)
        runner = self._runner(mocker)
        result = runner.run("проверь последние логи и исправь ошибку", raw=True)
        assert result == "Ответ"
        cmd = popen.call_args[0][0]
        assert "--model" in cmd
        assert cmd[-1] == "проверь последние логи и исправь ошибку"
        assert "от пользователя поступила команда" not in cmd[-1]
        assert popen.call_args[1]["cwd"] == REPO_ROOT

    def test_run_default_wraps_in_base_prompt(self, mocker):
        """Обычный режим: текст оборачивается в BASE_PROMPT, cwd — cli/."""
        proc = FakeProc(["Ответ"])
        popen = mocker.patch(
            "lib.opencode_cli.subprocess.Popen", return_value=proc)
        mocker.patch("lib.opencode_cli.os.path.isdir", return_value=True)
        runner = self._runner(mocker)
        runner.run("сделай громче")
        cmd = popen.call_args[0][0]
        assert "от пользователя поступила команда" in cmd[-1]
        assert "сделай громче" in cmd[-1]
        assert popen.call_args[1]["cwd"] == r"C:\cli"

    def test_run_raw_missing_repo_root_returns_none(self, mocker):
        """missing dir в dev-режиме (свой run_dir) даёт None + ошибку."""
        mocker.patch("lib.opencode_cli.os.path.isdir", return_value=False)
        runner = self._runner(mocker)
        assert runner.run("что-то", raw=True) is None
        error = runner._output.print_error.call_args[0][0]
        assert "Рабочая папка не найдена" in error

    def test_run_verbose_streams_lines_to_console(self, mocker):
        """verbose=True стримит строки CLI в print_info в реальном времени."""
        proc = FakeProc(["шаг 1", "\x1b[31mошибка: нет доступа\x1b[0m", "итог"])
        mocker.patch(
            "lib.opencode_cli.subprocess.Popen", return_value=proc)
        mocker.patch("lib.opencode_cli.os.path.isdir", return_value=True)
        runner = self._runner(mocker)
        result = runner.run("проверь", verbose=True)
        assert result == "шаг 1\nошибка: нет доступа\nитог"
        streamed = [
            c.args[0] for c in runner._output.print_info.call_args_list
        ]
        assert any(s == "[OpenCode>>] шаг 1" for s in streamed)
        assert any(s == "[OpenCode>>] ошибка: нет доступа" for s in streamed)
        assert any(s == "[OpenCode>>] итог" for s in streamed)

    def test_run_raw_implies_verbose(self, mocker):
        """dev-режим (raw=True) включает стрим без явного verbose."""
        proc = FakeProc(["сырой ответ <tag>"])
        mocker.patch(
            "lib.opencode_cli.subprocess.Popen", return_value=proc)
        mocker.patch("lib.opencode_cli.os.path.isdir", return_value=True)
        runner = self._runner(mocker)
        result = runner.run("что-то", raw=True)
        # raw=True → verbose=True по умолчанию: вывод не фильтруется
        assert "<tag>" in result
        streamed = [
            c.args[0] for c in runner._output.print_info.call_args_list
        ]
        assert any(s == "[OpenCode>>] сырой ответ <tag>" for s in streamed)

    def test_run_timeout_dumps_partial_output(self, mocker):
        """При таймауте в dev-режиме показывается накопленный вывод."""
        import time as _time

        class BlockingProc:
            """Отдаёт одну строку, затем блокирует ридер (процесс завис)."""

            def __init__(self):
                self._lines = iter(["начал делать\n"])
                self.poll_result = None
                self.returncode_value = 0
                self.killed = False
                self.stdout = self

            def readline(self):
                try:
                    return next(self._lines)
                except StopIteration:
                    _time.sleep(60)
                    return ""

            def poll(self):
                return self.poll_result

            def kill(self):
                self.killed = True

            def wait(self, timeout=5):
                self.poll_result = self.returncode_value
                return self.returncode_value

        proc = BlockingProc()
        prod = mocker.patch(
            "lib.opencode_cli.subprocess.Popen", return_value=proc)
        mocker.patch("lib.opencode_cli.os.path.isdir", return_value=True)
        runner = self._runner(mocker, timeout=0.01)
        result = runner.run("команда", raw=True)
        assert result is None
        assert prod.called
        streamed = [
            c.args[0] for c in runner._output.print_info.call_args_list
        ]
        assert any("Вывод до таймаута" in s for s in streamed)
        assert any("[OpenCode>>] начал делать" in s for s in streamed)

    def test_run_reports_empty_output(self, mocker):
        proc = FakeProc([], returncode=1)
        mocker.patch("lib.opencode_cli.subprocess.Popen", return_value=proc)
        mocker.patch("lib.opencode_cli.os.path.isdir", return_value=True)
        runner = self._runner(mocker)
        assert runner.run("команда") is None
