import pytest
import os
import shutil
import tempfile
from pathlib import Path
from lib.logger import Logger


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
        logger.log_command("тестовая команда")
        content = logger._log_file.read_text()
        assert "тестовая команда" in content

    def test_log_command_with_timestamp(self, temp_log_dir):
        logger = Logger()
        logger.log_command("команда")
        content = logger._log_file.read_text()
        parts = content.split(" ", 1)
        assert len(parts) >= 2

    def test_log_llm_user_message(self, temp_log_dir):
        logger = Logger()
        logger.log_llm("user", "Привет!")
        content = logger._llm_file.read_text()
        assert "[USER]" in content
        assert "Привет!" in content

    def test_log_llm_assistant_message(self, temp_log_dir):
        logger = Logger()
        logger.log_llm("assistant", "Как дела?")
        content = logger._llm_file.read_text()
        assert "[ASSISTANT]" in content
        assert "Как дела?" in content

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
