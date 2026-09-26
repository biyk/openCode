"""Тесты для исполнения скиллов (SkillRegistry.execute)."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from lib.skills.skills import SkillRegistry


class TestSkillRegistryExecution:
    """Тесты исполнения скиллов."""

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

    def test_execute_skill_success(self, tmp_path):
        """execute() успешно выполняет скилл open_url."""
        skill_data = {
            "name": "youtube",
            "phrases": ["открой ютуб"],
            "params": {},
            "steps": [{"action": "open_url", "params": {"url": "https://youtube.com"}}],
        }
        registry, _ = self._make_registry(tmp_path, {"youtube": skill_data})
        with patch("lib.skills.skill_actions.platform.system", return_value="windows"), \
             patch("lib.skills.skill_actions.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            result = registry.execute("youtube")
        assert result is True
        mock_run.assert_called_once()

    def test_execute_unknown_skill(self, tmp_path):
        """execute() возвращает False для неизвестного скилла."""
        registry, _ = self._make_registry(tmp_path)
        assert registry.execute("unknown") is False

    def test_execute_skill_missing_step_param(self, tmp_path):
        """execute() возвращает False, если шаг требует отсутствующий параметр."""
        skill_data = {
            "name": "param_skill",
            "phrases": ["с параметром"],
            "params": {},
            "steps": [{"action": "open_url", "params": {"url": "${missing}"}}],
        }
        registry, _ = self._make_registry(tmp_path, {"param_skill": skill_data})
        assert registry.execute("param_skill") is False

    def test_execute_skill_with_resolved_param(self, tmp_path):
        """execute() подставляет параметры из validated params в шаги."""
        skill_data = {
            "name": "dynamic_url",
            "phrases": ["открой ссылку"],
            "params": {"url": {"type": "str", "required": True}},
            "steps": [{"action": "open_url", "params": {"url": "${url}"}}],
        }
        registry, _ = self._make_registry(tmp_path, {"dynamic_url": skill_data})
        with patch("lib.skills.skill_actions.platform.system", return_value="windows"), \
             patch("lib.skills.skill_actions.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            result = registry.execute("dynamic_url", {"url": "https://test.com"})
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "https://test.com" in str(call_args)

    def test_validate_params_required_missing(self, tmp_path):
        """_validate_params возвращает None, если обязательный параметр отсутствует."""
        skill_data = {
            "name": "req_param",
            "phrases": ["нужно"],
            "params": {"req": {"type": "str", "required": True}},
            "steps": [],
        }
        registry, _ = self._make_registry(tmp_path, {"req_param": skill_data})
        assert registry.execute("req_param", {}) is False

    def test_validate_params_type_conversion(self, tmp_path):
        """_validate_params преобразует типы параметров."""
        skill_data = {
            "name": "typed",
            "phrases": ["типы"],
            "params": {"num": {"type": "int", "required": True}, "flt": {"type": "float"}},
            "steps": [],
        }
        registry, _ = self._make_registry(tmp_path, {"typed": skill_data})
        validated = registry._validate_params(skill_data["params"], {"num": "42", "flt": "3.14"})
        assert validated is not None
        assert validated["num"] == 42
        assert validated["flt"] == 3.14

    def test_validate_params_invalid_type(self, tmp_path):
        """_validate_params возвращает None при неверном типе."""
        skill_data = {
            "name": "bad_type",
            "phrases": ["плохой"],
            "params": {"num": {"type": "int", "required": True}},
            "steps": [],
        }
        registry, _ = self._make_registry(tmp_path, {"bad_type": skill_data})
        validated = registry._validate_params(skill_data["params"], {"num": "not_a_number"})
        assert validated is None

    def test_execute_run_cmd(self, tmp_path):
        """execute() выполняет run_cmd действие."""
        skill_data = {
            "name": "cmd_skill",
            "phrases": ["команда"],
            "params": {},
            "steps": [{"action": "run_cmd", "params": {"cmd": "echo hello"}}],
        }
        registry, _ = self._make_registry(tmp_path, {"cmd_skill": skill_data})
        with patch("lib.skills.skill_actions.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            result = registry.execute("cmd_skill")
        assert result is True
        mock_run.assert_called_once_with("echo hello", shell=True, check=True)

    def test_execute_run_cmd_failure(self, tmp_path):
        """execute() возвращает False при ошибке run_cmd."""
        skill_data = {
            "name": "fail_cmd",
            "phrases": ["провал"],
            "params": {},
            "steps": [{"action": "run_cmd", "params": {"cmd": "exit 1"}}],
        }
        registry, _ = self._make_registry(tmp_path, {"fail_cmd": skill_data})
        with patch("lib.skills.skill_actions.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")
            result = registry.execute("fail_cmd")
        assert result is False

    def test_execute_unknown_action(self, tmp_path):
        """execute() возвращает False для неизвестного действия."""
        skill_data = {
            "name": "unknown_action",
            "phrases": ["неизвестно"],
            "params": {},
            "steps": [{"action": "unknown_action", "params": {}}],
        }
        registry, _ = self._make_registry(tmp_path, {"unknown_action": skill_data})
        assert registry.execute("unknown_action") is False

    def test_validate_params_optional_missing(self, tmp_path):
        """_validate_params пропускает необязательные отсутствующие параметры."""
        skill_data = {
            "name": "optional",
            "phrases": ["опционально"],
            "params": {"opt": {"type": "str", "required": False}},
            "steps": [],
        }
        registry, _ = self._make_registry(tmp_path, {"optional": skill_data})
        validated = registry._validate_params(skill_data["params"], {})
        assert validated is not None
        assert "opt" not in validated

    def test_validate_params_float_error(self, tmp_path):
        """_validate_params возвращает None при неверном float."""
        skill_data = {
            "name": "bad_float",
            "phrases": ["плохой"],
            "params": {"flt": {"type": "float", "required": True}},
            "steps": [],
        }
        registry, _ = self._make_registry(tmp_path, {"bad_float": skill_data})
        validated = registry._validate_params(skill_data["params"], {"flt": "not_a_float"})
        assert validated is None

    def test_execute_step_exception(self, tmp_path):
        """_execute_step ловит исключения и возвращает False."""
        skill_data = {
            "name": "exception_skill",
            "phrases": ["исключение"],
            "params": {},
            "steps": [{"action": "unknown", "params": {}}],
        }
        registry, _ = self._make_registry(tmp_path, {"exception_skill": skill_data})
        with patch.object(registry, "_action_open_url", side_effect=Exception("boom")):
            result = registry.execute("exception_skill")
        assert result is False

    def test_get_skill_not_found(self, tmp_path):
        """get_skill возвращает None для неизвестного."""
        registry, _ = self._make_registry(tmp_path)
        assert registry.get_skill("ghost") is None
