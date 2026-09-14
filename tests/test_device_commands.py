import json
import os
import platform
import pytest
from lib.commands import CommandMatcher


class TestDeviceCommands:
    """Тесты для device-specific команд."""

    @pytest.fixture
    def device_commands_path(self):
        """Возвращает путь к commands.json устройства."""
        from lib.config_loader import get_device_commands_path
        hostname = platform.node()
        return get_device_commands_path(hostname)

    def test_commands_file_exists(self, device_commands_path):
        """Проверяет, что файл команд существует."""
        assert os.path.exists(device_commands_path), (
            f"Commands file not found: {device_commands_path}"
        )

    def test_commands_file_valid_json(self, device_commands_path):
        """Проверяет, что файл команд - валидный JSON."""
        with open(device_commands_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "commands" in data
        assert "match" in data

    def test_commands_have_platform_keys(self, device_commands_path):
        """Проверяет, что команды содержат ключи для разных платформ."""
        with open(device_commands_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        commands = data.get("commands", {})
        for cmd_id, cmd in commands.items():
            if isinstance(cmd, dict):
                assert "default" in cmd, f"Command {cmd_id} missing 'default' key"
            assert isinstance(cmd, (dict, str)), f"Command {cmd_id} has invalid type"

    def test_find_command_with_platform(self, device_commands_path):
        """Проверяет дословный поиск и shell-команду для текущей платформы."""
        matcher = CommandMatcher(device_commands_path)

        match_data = matcher._data.get("match", {})
        if not match_data:
            pytest.skip("No match patterns in commands file")

        first_id = list(match_data.keys())[0]
        first_pattern = match_data[first_id][0]
        # Теперь нужен триггер для активации команд
        found = matcher.find_literal_id(f"пожалуйста {first_pattern}")

        assert found == first_id, f"Command not found for pattern: {first_pattern}"
        result = matcher.get_command(found)

        if platform.system() == "Windows":
            assert "playerctl" not in (result or ""), (
                f"playerctl not available on Windows: {result}")
            assert "pactl" not in (result or ""), (
                f"pactl not available on Windows: {result}")

    def test_windows_commands_are_valid_powershell(self, device_commands_path):
        """Проверяет, что Windows команды не содержат ошибок."""
        if platform.system() != "Windows":
            pytest.skip("Windows-only test")

        with open(device_commands_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        commands = data.get("commands", {})
        for cmd_id, cmd in commands.items():
            if isinstance(cmd, dict):
                windows_cmd = cmd.get("windows") or cmd.get("default")
            else:
                windows_cmd = cmd

            if windows_cmd and "powershell" in windows_cmd.lower():
                assert "Get-AudioDevice" not in windows_cmd, (
                    f"Command {cmd_id} uses unavailable Get-AudioDevice"
                )

    def test_windows_addtype_is_valid(self, device_commands_path):
        """Проверяет, что Add-Type команды не вызывают предупреждений компилятора."""
        if platform.system() != "Windows":
            pytest.skip("Windows-only test")

        with open(device_commands_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        commands = data.get("commands", {})
        for cmd_id, cmd in commands.items():
            if isinstance(cmd, dict):
                windows_cmd = cmd.get("windows") or cmd.get("default")
            else:
                windows_cmd = cmd

            if windows_cmd and "Add-Type" in windows_cmd:
                assert "VK_MEDIA_PLAY_PAUSE" not in windows_cmd, (
                    f"Command {cmd_id}: unused variable VK_MEDIA_PLAY_PAUSE"
                )
                assert "VK_MEDIA_STOP" not in windows_cmd, (
                    f"Command {cmd_id}: unused variable VK_MEDIA_STOP"
                )
                assert "public class " in windows_cmd, (
                    f"Command {cmd_id}: missing class definition"
                )
                # Проверяем наличие .dll (может быть экранировано)
                normalized = windows_cmd.replace("\\", "")
                assert "user32.dll" in normalized or 'DllImport("user32' in normalized, (
                    f"Command {cmd_id}: missing .dll extension in DllImport"
                )

    def test_windows_file_commands_exist(self, device_commands_path):
        """Команды powershell -File ссылаются на существующие файлы."""
        import re
        from pathlib import Path
        repo_root = Path(device_commands_path).resolve().parents[2]
        with open(device_commands_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        commands = data.get("commands", {})
        found = 0
        for cmd_id, cmd in commands.items():
            if isinstance(cmd, dict):
                windows_cmd = cmd.get("windows") or cmd.get("default")
            else:
                windows_cmd = cmd
            if not windows_cmd or "-File" not in windows_cmd:
                continue
            match = re.search(r'-File\s+"([^"]+)"', windows_cmd)
            assert match, f"Command {cmd_id}: unparsable -File reference"
            found += 1
            assert (repo_root / match.group(1)).exists(), (
                f"Command {cmd_id}: missing file {match.group(1)}"
            )
        assert found > 0, "No -File commands found to check"
