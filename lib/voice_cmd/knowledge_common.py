# lib/voice_cmd/knowledge_common.py
"""Словарь статусов базы знаний и нормализация фразы (лист-модуль без цикла).

Отделён от knowledge.py, чтобы миксин разрешения (knowledge_resolve) и
обучение (knowledge_learn) импортировали константы, не смыкая круг.
"""

from __future__ import annotations

# Вид решения
COMMAND, START, FINISH = "command", "start", "finish"
# Статусы-корзины; подтверждённое решение не понижаем автозаписью,
# laya сильнее undefined.
CONFIRMED, LAYA, UNDEFINED = "confirmed", "laya", "undefined"
BUCKETS = (CONFIRMED, LAYA, UNDEFINED)
_RANK = {CONFIRMED: 3, LAYA: 2, UNDEFINED: 1}
# Top-level ключ карты синонимов задач: «остаток фразы → канонический заголовок».
SYNONYMS = "synonyms"


def normalize_core(text: str) -> str:
    """Нормализация фразы: нижний регистр, ё→е, схлопывание пробелов."""
    return " ".join(text.lower().replace("ё", "е").split())
