"""Поиск команд по совпадению (миксин матчера)."""

from difflib import SequenceMatcher
from typing import Optional

# Порог максимального совпадения команды с match-шаблоном (не угадывать).
MATCH_THRESHOLD = 0.9


def _normalize(text: str) -> str:
    """Нижний регистр, ё→е, схлопывание пробелов."""
    return " ".join(text.lower().replace("ё", "е").split())


def _similarity(a: str, b: str) -> float:
    """Сходство двух строк (0.0–1.0) через SequenceMatcher."""
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


class CommandMatchMixin:
    """Миксин CommandMatcher: core_phrase, find_command, find_literal_id."""

    def core_phrase(self, text: str) -> str:
        """Возвращает текст без триггерных слов (нормализованный).

        «алиса включи ютуб пожалуйста» → «включи ютуб».
        """
        self.reload()
        triggers = {_normalize(t) for t in self.triggers}
        tokens = [t for t in _normalize(text).split(" ") if t not in triggers]
        return " ".join(tokens)

    def _match_command(self, core: str) -> tuple[Optional[str], list[str], float]:
        """Ищет команду в кандидате-строке (без ключа).

        Команда — префикс строки (макс. совпадение ≥ MATCH_THRESHOLD
        с match-шаблоном). Слова после команды — настройки.
        Возвращает (cmd_id, настройки, оценка совпадения).
        """
        tokens = _normalize(core).split()
        if not tokens:
            return None, [], 0.0
        best_id = None
        best_score = 0.0
        best_len = 0
        for cmd_id, templates in self._data.get("match", {}).items():
            for template in templates:
                t_tokens = _normalize(template).split()
                n = len(t_tokens)
                if n == 0 or n > len(tokens):
                    continue
                phrase = " ".join(tokens[:n])
                score = _similarity(phrase, template)
                if score >= MATCH_THRESHOLD and (
                        score > best_score
                        or (score == best_score and n > best_len)):
                    best_id = cmd_id
                    best_score = score
                    best_len = n
        if best_id is None:
            return None, [], 0.0
        return best_id, tokens[best_len:], best_score

    def find_command(self, text: str) -> tuple[Optional[str], list[str]]:
        """Поиск команды уровня commands.json в ОДНОЙ строке.

        Триггер и команда должны стоять в одной строке: ядро строки
        (текст без триггеров) матчится на команду. Соседние строки не
        смотрим и следующую не ждём. Возвращает (cmd_id, настройки);
        (None, []) — команды в строке нет.
        """
        self.reload()
        if not self.has_trigger(text):
            return None, []
        cmd_id, settings, _score = self._match_command(
            self.core_phrase(text))
        return cmd_id, settings

    def settings_for(self, cmd_id: str) -> dict:
        """Возвращает секцию настроек команды {"слово": {"param": множитель}}."""
        return self._data.get("settings", {}).get(cmd_id, {})

    def find_literal_id(self, text: str) -> Optional[str]:
        """Возвращает id команды при ДОСЛОВНОМ совпадении (или None).

        Ядро фразы (текст без триггеров) должно в точности равняться
        одному из шаблонов. Подстроки НЕ считаются: «включи пожалуйста»
        не запускает playpause по шаблону «включи». Статусы здесь
        не проверяются — их смотрит вызывающий через missing_requires().
        """
        self.reload()
        if not self.has_trigger(text):
            return None
        core = self.core_phrase(text)
        if not core:
            return None
        for cmd_id, templates in self._data.get("match", {}).items():
            for template in templates:
                if _normalize(template) == core:
                    return cmd_id
        return None
