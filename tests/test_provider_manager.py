import json

import pytest

from lib.providers.manager import ProviderManager

_DEFAULT_PROVIDERS = [
    {
        "id": "omni",
        "name": "OmniRouter",
        "module": "lib.providers.omni",
        "class": "OmniRouterClient",
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "module": "lib.providers.openrouter",
        "class": "OpenRouterClient",
    },
]


def _write_config(tmp_path, active="omni", providers=None, include_active=True):
    """Записывает temp-конфиг провайдеров и возвращает его путь."""
    config = {"providers": providers or _DEFAULT_PROVIDERS}
    if include_active:
        config["active"] = active
    path = tmp_path / "providers.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return str(path)


class TestProviderManager:
    """Тесты для класса ProviderManager."""

    def test_init_uses_default_config_path(self):
        """Без config_path используется корневой providers.json проекта."""
        manager = ProviderManager()
        assert manager._config_path.endswith("providers.json")

    def test_init_loads_active_provider(self, tmp_path):
        """Активный провайдер загружается из конфига."""
        path = _write_config(tmp_path, active="openrouter")
        manager = ProviderManager(path)
        assert manager.get_active_provider_id() == "openrouter"

    def test_active_defaults_to_openrouter(self, tmp_path):
        """Без поля active используется openrouter."""
        path = _write_config(tmp_path, include_active=False)
        manager = ProviderManager(path)
        assert manager.get_active_provider_id() == "openrouter"

    def test_reload_updates_config(self, tmp_path):
        """reload() перечитывает конфиг и очищает кэш."""
        path = _write_config(tmp_path, active="omni")
        manager = ProviderManager(path)
        manager._providers["omni"] = object()
        _write_config(tmp_path, active="openrouter")
        manager.reload()
        assert manager.get_active_provider_id() == "openrouter"
        assert manager._providers == {}

    def test_set_active_provider(self, tmp_path):
        """set_active_provider сохраняет выбор в конфиг и чистит кэш."""
        path = _write_config(tmp_path, active="omni")
        manager = ProviderManager(path)
        manager._providers["omni"] = object()
        manager.set_active_provider("openrouter")
        assert manager.get_active_provider_id() == "openrouter"
        assert manager._providers == {}
        with open(path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["active"] == "openrouter"

    def test_set_active_provider_unknown_raises(self, tmp_path):
        """Неизвестный провайдер вызывает ValueError."""
        path = _write_config(tmp_path)
        manager = ProviderManager(path)
        with pytest.raises(ValueError):
            manager.set_active_provider("ghost")

    def test_get_available_providers(self, tmp_path):
        """get_available_providers возвращает список из конфига."""
        path = _write_config(tmp_path)
        manager = ProviderManager(path)
        providers = manager.get_available_providers()
        assert len(providers) == 2
        assert providers[0]["id"] == "omni"

    def test_get_client_returns_instance(self, tmp_path):
        """get_client возвращает экземпляр активного провайдера."""
        path = _write_config(tmp_path, active="omni")
        manager = ProviderManager(path)
        client = manager.get_client()
        assert client.name == "OmniRouter"

    def test_get_client_caches_instance(self, tmp_path):
        """Повторный get_client возвращает тот же экземпляр."""
        path = _write_config(tmp_path, active="omni")
        manager = ProviderManager(path)
        first = manager.get_client()
        second = manager.get_client()
        assert first is second

    def test_get_client_passes_kwargs(self, tmp_path):
        """kwargs передаются в конструктор клиента."""
        path = _write_config(tmp_path, active="omni")
        manager = ProviderManager(path)
        client = manager.get_client(history_limit=7, base_url="http://example.com/")
        assert client._history_limit == 7
        assert client._base_url == "http://example.com"

    def test_get_client_unknown_active_raises(self, tmp_path):
        """Активный id без записи в providers вызывает ValueError."""
        path = _write_config(tmp_path, active="ghost", providers=_DEFAULT_PROVIDERS)
        manager = ProviderManager(path)
        with pytest.raises(ValueError):
            manager.get_client()
