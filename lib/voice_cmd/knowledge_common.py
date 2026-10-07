# lib/voice_cmd/knowledge_common.py
"""Словарь статусов базы знаний и нормализация фразы (лист-модуль без цикла).

Отделён от knowledge.py, чтобы миксин разрешения (knowledge_resolve) и
обучение (knowledge_learn) импортировали константы, не смыкая круг.
"""

from __future__ import annotations

from datetime import date

# Вид решения
COMMAND, START, FINISH = "command", "start", "finish"
# Статусы-корзины; подтверждённое решение не понижаем автозаписью,
# laya сильнее undefined.
CONFIRMED, LAYA, UNDEFINED = "confirmed", "laya", "undefined"
BUCKETS = (CONFIRMED, LAYA, UNDEFINED)
_RANK = {CONFIRMED: 3, LAYA: 2, UNDEFINED: 1}
# Top-level ключ карты синонимов задач: «остаток фразы → канонический заголовок».
SYNONYMS = "synonyms"
# Когда запись попала в базу — «YYYY-MM-DD»; поле нужно досмотру, чтобы
# отделять свежие фразы от давно живущих (сортировка/фильтр «что нового»).
ADDED = "added"


def normalize_core(text: str) -> str:
    """Нормализация фразы: нижний регистр, ё→е, схлопывание пробелов."""
    return " ".join(text.lower().replace("ё", "е").split())


def today_str() -> str:
    """Сегодня как «YYYY-MM-DD» — стабильно сортируется лексикографически."""
    return date.today().isoformat()
