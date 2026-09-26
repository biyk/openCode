import pytest
import os
import shutil
import tempfile
from lib.core.logger import Logger


class TestLogger:
    """Тесты для класса Logger."""

    @pytest.fixture
    def temp_log_dir(self):
        """Создаёт временную директорию для логов."""
        tmpdir = tempfile.mkdtemp()
        original_cwd = os.getcwd()
        os.chdir(tmpdir)
        yield tmpdir
        os.chdir(original_cwd)
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_init_creates_log_directory(self, temp_log_dir):
        logger = Logger()
        assert logger._base_dir.exists()

    def test_init_creates_log_files(self, temp_log_dir):
        logger = Logger()
        assert logger._log_file is not None
        assert logger._llm_file is not None

    def test_log_command_creates_entry(self, temp_log_dir):
        logger = Logger()
        test_text = "test command"
        logger.log_command(test_text)
        content = logger._log_file.read_text()
        assert test_text in content

    def test_log_command_with_timestamp(self, temp_log_dir):
        logger = Logger()
        logger.log_command("команда")
        content = logger._log_file.read_text()
        parts = content.split(" ", 1)
        assert len(parts) >= 2

    def test_log_llm_user_message(self, temp_log_dir):
        logger = Logger()
        test_msg = "Hello!"
        logger.log_llm("user", test_msg)
        content = logger._llm_file.read_text()
        assert "[USER]" in content
        assert test_msg in content

    def test_log_llm_assistant_message(self, temp_log_dir):
        logger = Logger()
        test_msg = "How are you?"
        logger.log_llm("assistant", test_msg)
        content = logger._llm_file.read_text()
        assert "[ASSISTANT]" in content
        assert test_msg in content

    def test_get_llm_history_empty(self, temp_log_dir):
        logger = Logger()
        history = logger.get_llm_history()
        assert history == []

    def test_get_llm_history_with_messages(self, temp_log_dir):
        logger = Logger()
        logger.log_llm("user", "Вопрос")
        logger.log_llm("assistant", "Ответ")
        history = logger.get_llm_history()
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Вопрос"
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "Ответ"

    def test_get_llm_history_limit(self, temp_log_dir):
        logger = Logger()
        for i in range(15):
            logger.log_llm("user", f"msg{i}")
        history = logger.get_llm_history(limit=5)
        assert len(history) == 5

    def test_get_llm_history_ignores_command_logs(self, temp_log_dir):
        logger = Logger()
        logger.log_command("команда")
        logger.log_llm("user", "вопрос")
        history = logger.get_llm_history()
        assert len(history) == 1
        assert history[0]["role"] == "user"


class TestLatestLogs:
    """Хелперы для диагностики: поиск логов, хвост, история чата."""

    def _write(self, tmp_path, name, content, mtime):
        import os
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return str(path)

    def test_latest_logs_picks_newest(self, tmp_path):
        from lib.core.logger import latest_logs
        old = self._write(tmp_path, "commands_old.log", "a\n", 1000.0)
        new = self._write(tmp_path, "commands_new.log", "b\n", 2000.0)
        self._write(tmp_path, "llm_x.log", "[USER] hi\n", 1500.0)
        self._write(tmp_path, "notes.txt", "x\n", 3000.0)
        cmd, llm = latest_logs(str(tmp_path))
        assert cmd == new
        assert llm.endswith("llm_x.log")
        assert old != cmd

    def test_latest_logs_missing(self, tmp_path):
        from lib.core.logger import latest_logs
        assert latest_logs(str(tmp_path / "nodir")) == (None, None)
        assert latest_logs(str(tmp_path)) == (None, None)

    def test_tail_lines(self, tmp_path):
        from lib.core.logger import tail_lines
        path = self._write(
            tmp_path, "f.log", "l1\n\nl2\nl3\n", 1000.0)
        assert tail_lines(path, 2) == ["l2", "l3"]
        assert tail_lines(str(tmp_path / "nope.log"), 5) == []

    def test_read_llm_history(self, tmp_path):
        from lib.core.logger import read_llm_history
        path = self._write(
            tmp_path, "llm.log",
            "[USER] вопрос\n[ASSISTANT] ответ\nмусор\n[USER] ещё\n",
            1000.0)
        history = read_llm_history(path, limit=10)
        assert history == [
            {"role": "user", "content": "вопрос"},
            {"role": "assistant", "content": "ответ"},
            {"role": "user", "content": "ещё"},
        ]
        assert len(read_llm_history(path, limit=2)) == 1
