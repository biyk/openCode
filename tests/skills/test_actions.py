"""Тесты для действий скиллов (open_url, run_cmd) и edge cases."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from lib.skills import SkillRegistry


class TestSkillRegistryActions:
    """Тесты конкретных действий скиллов."""

    def _make_registry(self, tmp_path, skills=None):
        """Создаёт реестр с временной папкой и опциональными скиллами."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        if skills:
            for name, data in skills.items():
                (tmp_path / "skills" / f"{name}.json").write_text(
                    json.dumps(data), encoding="utf-8"
                )
        return SkillRegistry(skills_dir=str(tmp_path / "skills")), tmp_path / "skills"

    def test_action_open_url_missing_url(self, tmp_path):
        """_action_open_url возвращает False если нет url."""
        registry, _ = self._make_registry(tmp_path)
        assert registry._action_open_url({}) is False

    def test_action_open_url_windows(self, tmp_path):
        """_action_open_url работает на windows."""
        registry, _ = self._make_registry(tmp_path)
        with patch("lib.skills.platform.system", return_value="windows"), \
             patch("lib.skills.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            result = registry._action_open_url({"url": "https://example.com"})
        assert result is True
        mock_run.assert_called_once_with(
            ["cmd", "/c", "start", "", "https://example.com"], check=True
        )

    def test_action_open_url_darwin(self, tmp_path):
        """_action_open_url работает на darwin."""
        registry, _ = self._make_registry(tmp_path)
        with patch("lib.skills.platform.system", return_value="darwin"), \
             patch("lib.skills.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            result = registry._action_open_url({"url": "https://example.com"})
        assert result is True
        mock_run.assert_called_once_with(["open", "https://example.com"], check=True)

    def test_action_open_url_linux(self, tmp_path):
        """_action_open_url работает на linux."""
        registry, _ = self._make_registry(tmp_path)
        with patch("lib.skills.platform.system", return_value="linux"), \
             patch("lib.skills.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            result = registry._action_open_url({"url": "https://example.com"})
        assert result is True
        mock_run.assert_called_once_with(
            ["xdg-open", "https://example.com"], check=True
        )

    def test_action_open_url_called_process_error(self, tmp_path):
        """_action_open_url возвращает False при ошибке subprocess."""
        registry, _ = self._make_registry(tmp_path)
        with patch("lib.skills.platform.system", return_value="windows"), \
             patch("lib.skills.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")
            result = registry._action_open_url({"url": "https://example.com"})
        assert result is False

    def test_action_run_cmd_missing_cmd(self, tmp_path):
        """_action_run_cmd возвращает False если нет cmd."""
        registry, _ = self._make_registry(tmp_path)
        assert registry._action_run_cmd({}) is False

    def test_action_run_cmd_exception(self, tmp_path):
        """_action_run_cmd ловит исключения subprocess."""
        registry, _ = self._make_registry(tmp_path)
        with patch("lib.skills.subprocess.run",
                   side_effect=subprocess.CalledProcessError(1, "cmd")):
            result = registry._action_run_cmd({"cmd": "echo test"})
        assert result is False

    def test_execute_step_exception_handler(self, tmp_path):
        """_execute_step ловит исключение в действии."""
        skill_data = {
            "name": "boom",
            "phrases": ["бам"],
            "params": {},
            "steps": [{"action": "open_url", "params": {"url": "https://example.com"}}],
        }
        registry, _ = self._make_registry(tmp_path, {"boom": skill_data})
        with patch.object(SkillRegistry, "_action_open_url",
                          side_effect=Exception("boom")):
            result = registry.execute("boom")
        assert result is False

    def test_execute_unknown_skill(self, tmp_path):
        """execute возвращает False для неизвестного скилла."""
        registry, _ = self._make_registry(tmp_path)
        assert registry.execute("nonexistent") is False

    def test_get_skill_not_found(self, tmp_path):
        """get_skill возвращает None для неизвестного."""
        registry, _ = self._make_registry(tmp_path)
        assert registry.get_skill("ghost") is None
