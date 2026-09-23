"""Тесты console opencode: чистка вывода агента."""


from unittest.mock import MagicMock
from lib.opencode_cli import OpenCodeCliRunner


class TestRunnerClean:
    """ANSI, шум, tool-call разметка."""

    def _runner(self, mocker, **kwargs):
        mocker.patch("lib.opencode_cli._find_opencode_exe", return_value=r"C:\x\opencode.exe")
        return OpenCodeCliRunner(cli_dir=r"C:\cli", output=mocker.MagicMock(), **kwargs)

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
