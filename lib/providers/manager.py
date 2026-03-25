import os
import json
import importlib
from typing import Optional


class ProviderManager:
    """Менеджер LLM провайдеров с поддержкой переключения."""

    def __init__(self, config_path: Optional[str] = None):
        self._config_path = config_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "providers.json"
        )
        self._providers: dict = {}
        self._active_provider_id: Optional[str] = None
        self._load_config()

    def _load_config(self) -> None:
        """Загружает конфигурацию провайдеров."""
        with open(self._config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        self._active_provider_id = config.get("active", "openrouter")

    def reload(self) -> None:
        """Перезагружает конфигурацию."""
        self._load_config()
        self._providers.clear()

    def get_active_provider_id(self) -> str:
        """Возвращает ID активного провайдера."""
        return self._active_provider_id

    def set_active_provider(self, provider_id: str) -> None:
        """Устанавливает активного провайдера и сохраняет в конфиг."""
        with open(self._config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        if not any(p["id"] == provider_id for p in config["providers"]):
            raise ValueError(f"Провайдер {provider_id} не найден")

        config["active"] = provider_id
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        self._active_provider_id = provider_id
        self._providers.clear()

    def get_available_providers(self) -> list[dict]:
        """Возвращает список доступных провайдеров."""
        with open(self._config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get("providers", [])

    def get_client(self, **kwargs):
        """Возвращает экземпляр активного LLM провайдера."""
        if self._active_provider_id in self._providers:
            return self._providers[self._active_provider_id]

        with open(self._config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        provider_config = next(
            (p for p in config["providers"] if p["id"] == self._active_provider_id),
            None
        )
        if not provider_config:
            raise ValueError(f"Провайдер {self._active_provider_id} не найден")

        module = importlib.import_module(provider_config["module"])
        client_class = getattr(module, provider_config["class"])
        client = client_class(**kwargs)
        self._providers[self._active_provider_id] = client
        return client
