"""Тесты для функции get_skills_dir."""

import platform
from unittest.mock import patch

from lib.skills import get_skills_dir


class TestGetSkillsDir:
    """Тесты для функции get_skills_dir."""

    def test_returns_path_with_hostname(self, monkeypatch):
        """get_skills_dir возвращает путь с папкой skills."""
        monkeypatch.setattr(platform, "node", lambda: "TEST-HOST")
        with patch("lib.config_loader.get_device_commands_path",
                   lambda host: f"/config/{host}/commands.json"):
            path = get_skills_dir()
        assert path.name == "skills"
        assert "TEST-HOST" in str(path)
