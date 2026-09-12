"""Классификация голосовой команды через LLM (мини-слой)."""

from typing import Any, Callable, Optional


class IntentClassifier:
    """Определяет, какой команде из списка соответствует распознанный текст.

    Заменяет наивный fuzzy-матчинг: полагается на LLM (омни-роутер, модель
    auto/fast). В промпт передаются идентификаторы команд с примерами фраз
    и флаг воспроизведения медиа. LLM отвечает либо id команды (исполняем),
    либо NONE (тогда текст уходит в обычный диалог с LLM).
    """

    def __init__(
        self,
        commands: dict[str, list[str]],
        llm: Any,
        media_probe: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._commands = commands
        self._llm = llm
        self._media_probe = media_probe or (lambda: False)

    def _build_prompt(self, text: str) -> str:
        """Собирает промпт с доступными командами и флагом медиа."""
        command_list = "\n".join(
            f"- {cmd_id}: {', '.join(phrases)}"
            for cmd_id, phrases in self._commands.items()
        )
        media = "да" if self._media_probe() else "нет"
        return (
            "Ты — классификатор голосовых команд. Доступные команды:\n"
            f"{command_list}\n"
            f"Сейчас воспроизводится медиа (музыка/видео): {media}.\n"
            f"Запрос пользователя: «{text}»\n"
            "Если запрос соответствует одной из команд — ответь ТОЛЬКО её "
            "идентификатором (одно слово, без кавычек).\n"
            "Если запрос — команда управления громкостью или "
            "воспроизведением, но медиа сейчас не воспроизводится — ответь NONE.\n"
            "Если запрос не соответствует ни одной команде — ответь ровно NONE."
        )

    def detect(self, text: str) -> Optional[str]:
        """Возвращает id команды из списка или None, если ничего не подходит."""
        if not text.strip() or not self._commands:
            return None
        raw = self._llm.ask(self._build_prompt(text))
        if not raw:
            return None
        candidate = raw.strip().lower().strip('"').strip("«»").strip()
        if candidate in self._commands:
            return candidate
        return None
