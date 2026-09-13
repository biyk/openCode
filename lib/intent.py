"""Классификация голосовой команды через LLM (мини-слой)."""

from typing import Any, Callable, Optional


class IntentClassifier:
    """Определяет, какой команде из списка соответствует распознанный текст.

    Полагается на LLM: в промпт передаются триггеры, идентификаторы команд
    с примерами фраз, требуемые статусы и их текущие значения. LLM отвечает
    либо id команды (исполняем), либо NONE (тогда текст уходит в обычный
    диалог с LLM). Распознавание речи с ошибками («ютюб» вместо «ютуб»)
    разбирает тоже LLM, дословный матчинг — не её задача.
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

    def _build_prompt(self, text: str,
                      context: Optional[dict] = None) -> str:
        """Собирает промпт с доступными командами и флагом медиа."""
        if context is not None:
            return self._build_context_prompt(text, context)
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

    def _build_context_prompt(self, text: str, context: dict) -> str:
        """Промпт с триггерами, командами, статусами и заблокированными."""
        triggers = ", ".join(context.get("triggers", [])) or "—"
        requires = context.get("requires", {})
        statuses = context.get("statuses", {})
        lines = []
        for cmd_id, phrases in self._commands.items():
            req = requires.get(cmd_id, [])
            req_str = ", ".join(req) if req else "нет"
            lines.append(f"- {cmd_id}: {', '.join(phrases)}; требует: {req_str}")
        status_str = ", ".join(
            f"{name}={'вкл' if on else 'выкл'}"
            for name, on in statuses.items()
        ) or "нет данных"
        blocked = context.get("blocked", [])
        if blocked:
            blocked_str = "; ".join(
                f"{bid} (нет: {', '.join(missing)})"
                for bid, missing in blocked
            )
        else:
            blocked_str = "нет"
        return (
            "Ты — классификатор голосовых команд. "
            "Отвечай ТОЛЬКО id команды или ровно NONE.\n"
            f"Активные триггерные слова: {triggers}.\n"
            "Доступные команды:\n"
            + "\n".join(lines) + "\n"
            f"Текущие статусы: {status_str}.\n"
            f"Заблокированы нехваткой статусов: {blocked_str}.\n"
            f"Запрос пользователя: «{text}»\n"
            "Правила:\n"
            "1. Дословное совпадение с командой — её id.\n"
            "2. Ошибки распознавания речи (похожие слова, перепутанный "
            "порядок) — самый похожий id.\n"
            "3. Предпочитай команды, чьи требования выполнены.\n"
            "4. Иначе — ровно NONE."
        )

    def detect(self, text: str,
               context: Optional[dict] = None) -> Optional[str]:
        """Возвращает id команды из списка или None, если ничего не подходит."""
        if not text.strip() or not self._commands:
            return None
        raw = self._llm.ask(self._build_prompt(text, context))
        if not raw:
            return None
        candidate = raw.strip().lower().strip('"').strip("«»").strip()
        if candidate in self._commands:
            return candidate
        return None
