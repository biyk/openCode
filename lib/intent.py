"""Классификация голосовой команды через LLM (мини-слой)."""

import re
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
            "3. Выбирай id ПО СМЫСЛУ запроса, даже если требования команды "
            "сейчас не выполнены, — проверку статусов выполняет программа, "
            "а не ты.\n"
            "4. Иначе — ровно NONE.\n"
            "Ответ — ровно одно слово, без объяснений и лишних строк."
        )

    def detect(self, text: str,
               context: Optional[dict] = None) -> Optional[str]:
        """Возвращает id команды из списка или None, если ничего не подходит.

        Если провайдер умеет classify() (гонка) — классификация идёт через
        него: без записи в историю и с пропуском NONE-ответов. Иначе —
        обычный ask() (старое поведение для одиночных провайдеров).
        """
        if not text.strip() or not self._commands:
            return None
        prompt = self._build_prompt(text, context)
        classify = getattr(self._llm, "classify", None)
        if callable(classify):
            raw = classify(prompt)
        else:
            raw = self._llm.ask(prompt)
        if not raw or not isinstance(raw, str):
            return None
        return self._extract_id(raw)

    def _extract_id(self, raw: str) -> Optional[str]:
        """Достаёт id команды из ответа LLM, даже с мусором вокруг.

        Большая модель иногда дописывает объяснения после id
        («playpause\\n\\nПравила...») — ищем id сначала строго,
        потом первое слово, потом как целое слово (раннее вхождение).
        """
        text = raw.strip().lower().strip('"').strip("«»").strip()
        if text in self._commands:
            return text
        if text == "none":
            return None
        first_line = text.split("\n", 1)[0].strip().strip('"').strip("«»")
        if first_line in self._commands:
            return first_line
        if first_line == "none":
            return None
        first_word = re.split(r"\s+", first_line, maxsplit=1)[0]
        first_word = first_word.strip(".,;:!?\"'«»()[]")
        if first_word in self._commands:
            return first_word
        if first_word == "none":
            return None
        best: Optional[str] = None
        best_pos: Optional[int] = None
        for cmd_id in self._commands:
            match = re.search(r"(?<![\w-])" + re.escape(cmd_id) + r"(?![\w-])",
                              text)
            if match and (best_pos is None or match.start() < best_pos):
                best, best_pos = cmd_id, match.start()
        return best
