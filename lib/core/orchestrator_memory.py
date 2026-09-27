"""Авто-кандидаты базы знаний и выполнение команд (миксин оркестратора)."""

from typing import Optional


class OrchestratorMemoryMixin:
    """Миксин Orchestrator: laya-кандидаты, undefined-корзина, контекст LLM."""

    def _execute_with_settings(self, cmd_id: str,
                               settings: list[str]) -> None:
        """Выполняет команду с настройками (если они есть)."""
        if settings:
            self._matcher.execute_by_id(cmd_id, tuple(settings))
        else:
            self._matcher.execute_by_id(cmd_id)

    def _remember_candidate(self, text: str, cmd_id: str,
                            literal_id: Optional[str]) -> None:
        """Недословный авто-кандидат → laya-корзина базы знаний на досмотр.

        Дословные фразы учить не нужно — они уже шаблоны commands.json.
        """
        if literal_id is not None:
            return
        knowledge = getattr(self, "_knowledge", None)
        if knowledge is None:
            return
        core = self._matcher.core_phrase(text)
        if core:
            knowledge.record_laya(core, cmd_id)

    def _record_undefined(self, text: str) -> None:
        """Ничего не распознано — фраза в корзину undefined доски знаний."""
        knowledge = getattr(self, "_knowledge", None)
        if knowledge is None:
            return
        core = self._matcher.core_phrase(text)
        if core:
            knowledge.record_undefined(core)

    def _llm_context(self,
                     blocked: list[tuple[str, list[str]]]) -> dict:
        """Контекст для LLM-классификатора: триггеры, команды, статусы."""
        return {
            "triggers": list(self._matcher.triggers),
            "statuses": self._matcher.status_snapshot(),
            "requires": self._matcher.requires_map(),
            "blocked": [(bid, list(missing)) for bid, missing in blocked],
        }
