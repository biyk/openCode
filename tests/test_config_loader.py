import pytest
import os
from lib.config_loader import get_device_commands_path


class TestConfigLoader:
    """Тесты для модуля config_loader."""

    def test_get_device_commands_path_none_returns_default(self):
        result = get_device_commands_path(None)
        normalized = result.replace("\\", "/")
        assert normalized.endswith("targets/commands.json")

    def test_get_device_commands_path_contains_device_name(self):
        result = get_device_commands_path("my_pc")
        assert "my_pc" in result
        normalized = result.replace("\\", "/")
        assert normalized.endswith("commands.json")

    def test_get_device_commands_path_returns_string(self):
        result = get_device_commands_path("test_device")
        assert isinstance(result, str)
        normalized = result.replace("\\", "/")
        assert "targets" in normalized
        assert "test_device" in result
