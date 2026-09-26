"""Доступ к секциям конфига commands.json (миксин матчера)."""


class CommandConfigMixin:
    """Миксин CommandMatcher: llm/intent/match/requires/provides/statuses."""

    def get_llm_config(self) -> dict:
        """Возвращает конфигурацию для LLM."""
        return self._data.get("llm", {})

    def get_intent_config(self) -> dict:
        """Возвращает конфигурацию интеллектуального классификатора команд."""
        return self._data.get("intent", {})

    def get_decision_config(self) -> dict:
        """Возвращает конфигурацию decision-слоя (Laya).

        Секция `decision` в commands.json: url сервера, порог confidence,
        критерии команд и опциональный auto_launch (exe/модель/порт).
        """
        return self._data.get("decision", {})

    def match_config(self) -> dict:
        """Возвращает словарь {command_id: [фразы]} для классификатора."""
        return self._data.get("match", {})

    def get_skills_config(self) -> dict:
        """Возвращает конфигурацию скиллов."""
        return self._data.get("skills", {})

    def get_opencode_cli_config(self) -> dict:
        """Возвращает конфигурацию фолбэка в console opencode."""
        return self._data.get("opencode_cli", {})

    def get_google_config(self) -> dict:
        """Возвращает конфигурацию интеграции Google (calendar/tasks)."""
        return self._data.get("google", {})

    def get_shopping_config(self) -> dict:
        """Возвращает секцию `shopping` (таблица списка покупок + dedup).

        Ключи: spreadsheet_id, sheet_name, sheet_id (gid листа) и
        dedup {enabled, fuzzy, threshold} — поиск дубликатов при
        добавлении; по умолчанию выключен.
        """
        return self._data.get("shopping", {})

    def requires_map(self) -> dict:
        """Возвращает {command_id: [статусы]} — условия запуска команд."""
        return self._data.get("requires", {})

    def provides_map(self) -> dict:
        """Возвращает {command_id: [статусы]} — статусы после успеха."""
        return self._data.get("provides", {})

    def sequences(self) -> dict:
        """Возвращает {sequence_id: {steps: [...]}} составных команд."""
        return self._data.get("sequences", {})

    def requires_for(self, cmd_id: str) -> list[str]:
        """Возвращает статусы, требуемые для запуска команды."""
        requires = self.requires_map().get(cmd_id, [])
        return list(requires)

    def provides_for(self, cmd_id: str) -> list[str]:
        """Возвращает статусы, выставляемые после успеха команды."""
        provides = self.provides_map().get(cmd_id, [])
        return list(provides)

    def needs_text(self, cmd_id: str) -> bool:
        """True, если шаблон команды использует {{text}} (свободный текст)."""
        cmd = self._data.get("commands", {}).get(cmd_id)
        if cmd is None:
            return False
        if isinstance(cmd, str):
            return "{{text}}" in cmd
        templates = (cmd.get(k) for k in
                     ("linux", "windows", "darwin", "default"))
        return any("{{text}}" in t for t in templates if isinstance(t, str))

    def missing_requires(self, cmd_id: str) -> list[str]:
        """Возвращает невыполненные requires команды (пусто = можно)."""
        if self._status_store is None or not self._status_store.enabled:
            return []
        return self._status_store.ensure(self.requires_for(cmd_id))

    def need_message(self, name: str) -> str:
        """Человекочитаемое сообщение при отсутствии статуса."""
        if self._status_store is not None:
            return self._status_store.need_message(name)
        return f"Нужен статус: {name}"

    def status_snapshot(self) -> dict[str, bool]:
        """Текущие статусы (пусто, если хранилище не подключено)."""
        if self._status_store is None:
            return {}
        return self._status_store.snapshot()
