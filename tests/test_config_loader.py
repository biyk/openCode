from lib import config_loader
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

    def test_get_device_commands_path_copies_default(self, tmp_path, monkeypatch):
        """Если файла устройства нет — создаётся папка и копируется дефолт."""
        fake_base = tmp_path / "repo"
        monkeypatch.setattr(
            config_loader,
            "__file__",
            str(fake_base / "lib" / "config_loader.py"),
        )
        targets_dir = fake_base / "targets"
        targets_dir.mkdir(parents=True)
        default_file = targets_dir / "commands.json"
        default_file.write_text('{"commands": {}}', encoding="utf-8")

        result = get_device_commands_path("host_2")

        device_file = targets_dir / "host_2" / "commands.json"
        assert result.replace("\\", "/") == str(device_file).replace("\\", "/")
        assert device_file.exists()
        assert device_file.read_text(encoding="utf-8") == '{"commands": {}}'

    def test_get_device_commands_path_keeps_existing(self, tmp_path, monkeypatch):
        """Если файл устройства уже есть — он не перезаписывается."""
        fake_base = tmp_path / "repo"
        monkeypatch.setattr(
            config_loader,
            "__file__",
            str(fake_base / "lib" / "config_loader.py"),
        )
        device_file = fake_base / "targets" / "host_3" / "commands.json"
        device_file.parent.mkdir(parents=True)
        device_file.write_text('{"custom": true}', encoding="utf-8")

        result = get_device_commands_path("host_3")

        assert result.replace("\\", "/") == str(device_file).replace("\\", "/")
        assert device_file.read_text(encoding="utf-8") == '{"custom": true}'

    def test_get_device_commands_path_copy_skips_if_no_default(
            self, tmp_path, monkeypatch):
        """Если дефолтного файла нет — копирование пропускается."""
        fake_base = tmp_path / "repo"
        monkeypatch.setattr(
            config_loader,
            "__file__",
            str(fake_base / "lib" / "config_loader.py"),
        )
        (fake_base / "targets").mkdir(parents=True)

        result = get_device_commands_path("host_4")

        device_file = fake_base / "targets" / "host_4" / "commands.json"
        assert result.replace("\\", "/") == str(device_file).replace("\\", "/")
        assert not device_file.exists()

    def test_get_device_commands_path_existing_file(self):
        """Если файл устройства существует — возвращается его путь."""
        result = get_device_commands_path("FLTP-5i3-16512")
        assert "FLTP-5i3-16512" in result
