"""Обучение алиасам голосом и выполнение команд (миксин оркестратора)."""

from typing import Optional

from lib.core.errors import swallowed


class OrchestratorMemoryMixin:
    """Миксин Orchestrator: «запомни»/«забудь», кандидаты, контекст LLM."""

    def _execute_with_settings(self, cmd_id: str,
                               settings: list[str]) -> None:
        """Выполняет команду с настройками (если они есть)."""
        if settings:
            self._matcher.execute_by_id(cmd_id, tuple(settings))
        else:
            self._matcher.execute_by_id(cmd_id)

    def _remember_candidate(self, text: str, cmd_id: str,
                            literal_id: Optional[str]) -> None:
        """Сохраняет авто-кандидата в pending (только для недословных).

        Дословные фразы учить не нужно — они уже шаблоны. Запоминает
        последнее разрешение для команды «запомни» без аргументов.
        """
        if self._aliases is None:
            return
        core = self._matcher.core_phrase(text)
        self._last_resolution = (core, cmd_id)
        if literal_id is None and core:
            self._aliases.add(core, cmd_id, confirmed=False)

    def _known_ids(self) -> set[str]:
        """Все известные id команд (включая sequences)."""
        ids = set(self._matcher.match_config())
        try:
            ids.update(self._matcher.sequences())
        except Exception as e:
            swallowed("orchestrator.sequences", e)
        return ids

    def _say(self, message: str) -> None:
        """Короткое голосовое подтверждение."""
        self._output.print_info(f"[Memory] {message}")
        self._speaking = True
        self._abort_playback.clear()
        self._speak_async(message)

    def _handle_memory_command(self, text: str) -> bool:
        """Обрабатывает «запомни»/«забудь». Возвращает True, если это они."""
        core = self._matcher.core_phrase(text)
        if not core:
            return False
        if core == "запомни" or core.startswith("запомни "):
            self._remember_voice(core)
            return True
        if core == "забудь" or core.startswith("забудь "):
            self._forget_voice(core)
            return True
        return False

    def _remember_voice(self, core: str) -> None:
        """Голосовое обучение: «запомни» / «запомни X это Y»."""
        assert self._aliases is not None
        rest = core[len("запомни"):].strip()
        if not rest:
            # Без аргументов — подтвердить последнее разрешение.
            if self._last_resolution is None:
                self._say("Нечего запоминать")
                return
            phrase, cmd_id = self._last_resolution
            if self._aliases.resolve(phrase) == cmd_id:
                self._say("Уже запомнила")
                return
            confirmed = self._aliases.confirm(phrase)
            if confirmed is not None:
                self._say(f"Запомнила: {phrase} это {confirmed}")
                return
            self._aliases.add(phrase, cmd_id, confirmed=True)
            self._say(f"Запомнила: {phrase} это {cmd_id}")
            return
        if " это " in rest:
            phrase, _, cmd_id = rest.partition(" это ")
            phrase, cmd_id = phrase.strip(), cmd_id.strip()
            if not phrase or not cmd_id:
                self._say("Не поняла, что запомнить")
                return
            if cmd_id not in self._known_ids():
                self._say(f"Не знаю команду {cmd_id}")
                return
            self._aliases.add(phrase, cmd_id, confirmed=True)
            self._say(f"Запомнила: {phrase} это {cmd_id}")
            return
        self._say("Скажи: запомни, что именно и какая команда")

    def _forget_voice(self, core: str) -> None:
        """Голосовое удаление: «забудь X»."""
        assert self._aliases is not None
        rest = core[len("забудь"):].strip()
        if not rest:
            self._say("Скажи, что забыть")
            return
        if self._aliases.forget(rest):
            self._say(f"Забыла: {rest}")
        else:
            self._say("Такого не помню")

    def _llm_context(self,
                     blocked: list[tuple[str, list[str]]]) -> dict:
        """Контекст для LLM-классификатора: триггеры, команды, статусы."""
        return {
            "triggers": list(self._matcher.triggers),
            "statuses": self._matcher.status_snapshot(),
            "requires": self._matcher.requires_map(),
            "blocked": [(bid, list(missing)) for bid, missing in blocked],
        }
