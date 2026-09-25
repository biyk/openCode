"""Поиск дубликата задачи перед добавлением: строгое совпадение → Laya.

Строгое совпадение нормализованных названий отсекается без модели.
Если строгого нет — Laya вопросом-выбором проверяет, не сводится ли
новая задача к одной из существующих; список режем на пачки под лимит
вариантов сервера (laya.max_opts). Кандидат из пачки принимается любым
(любой выбор не none), но решение даёт только подтверждающий парный
вопрос: он надёжнее, чем аргмакс большой пачки. Laya недоступна или
не подтвердила дубликат — задача считается новой (добавление не
блокируется).
"""

from typing import Callable, Optional

from lib.tasks_parse import _normalize

# Порог подтверждающего парного вопроса (калибровка на живом сервере):
# near-дубликаты >= 0.20, ложные семантически близкие пары <= 0.174
# («убраться в комнате» vs «Инвентаризация. Коробки» = 0.1739).
DUP_THRESHOLD = 0.19
# Вопрос по пачке — только кандидат: годится любой выбор не none
# (уверенность на 15 вариантах шумная, ~0.02-0.9).
BATCH_THRESHOLD = 0.0
# Лимит laya.max_opts: сервер принимает не больше 16 вариантов в вопросе.
MAX_OPTS = 16
# Названий на вопрос: остальные варианты занимает none (добавляет detect()).
BATCH_OPTS = MAX_OPTS - 1
# Не спрашиваем модель о десятках задач за раз.
MAX_EXISTING = 40
NONE_DESCRIPTION = "новой задачи нет в списке — она уникальна"
DUP_INSTRUCTIONS = (
    "Выбери открытую задачу из списка, которую повторяет новая задача "
    "(то же действие). Если не повторяет — none: " + NONE_DESCRIPTION + "."
)
PAIR_INSTRUCTIONS = (
    "Новая задача повторяет открытую задачу (то же действие)? Если "
    "повторяет — выбери её, если это разные задачи — none."
)
PAIR_NONE = "это разные задачи"


def find_duplicate(title: str, existing: list[dict],
                   get_decision: Optional[Callable[[], object]] = None,
                   ) -> Optional[dict]:
    """Ищет дубликат среди existing: exact, затем вопрос Laya.

    Возвращает {"id", "title", "method"} (method: exact|laya) или None.
    get_decision — фабрика LayaDecision (вызывается лениво, только
    когда exact не нашёлся и есть варианты); None — Laya не спрашиваем.
    """
    query = _normalize(title)
    if not query:
        return None
    for task in existing:
        if _normalize(str(task.get("title", ""))) == query:
            return _hit(task, "exact")
    options = [t for t in existing if t.get("title")][:MAX_EXISTING]
    if not options or get_decision is None:
        return None
    decision = get_decision()
    if decision is None:
        return None
    for start in range(0, len(options), BATCH_OPTS):
        task = _ask_laya(decision, title, options[start:start + BATCH_OPTS])
        if task is not None and _confirm(decision, title, task):
            return _hit(task, "laya")
    return None


def _ask_laya(decision, title: str, batch: list[dict]) -> Optional[dict]:
    """Один вопрос-выбор по пачке задач; кандидат или None.

    Критерии — сами названия (значение — описание «открытая задача: …»):
    на такие ключи Laya отвечает надёжнее, чем на индексы t0..tN.
    """
    criteria = {str(t["title"]): f"открытая задача: {t['title']}"
                for t in batch}
    criteria["none"] = NONE_DESCRIPTION
    verdict = decision.detect(
        f"Новая задача: {title}", criteria=criteria,
        instructions=DUP_INSTRUCTIONS, threshold=BATCH_THRESHOLD)
    return _pick(batch, verdict)


def _confirm(decision, title: str, task: dict) -> bool:
    """Парный вопрос: новая задача и кандидат — одно и то же?"""
    name = str(task["title"])
    verdict = decision.detect(
        f"Новая задача: {title}",
        criteria={name: f"открытая задача: {name}", "none": PAIR_NONE},
        instructions=PAIR_INSTRUCTIONS, threshold=DUP_THRESHOLD)
    return bool(verdict) and verdict[0] == name


def _pick(batch: list[dict], verdict: Optional[tuple]) -> Optional[dict]:
    """Выбор Laya (название задачи) → запись из batch; None мимо."""
    if verdict is None:
        return None
    for task in batch:
        if str(task["title"]) == verdict[0]:
            return task
    return None


def _hit(task: dict, method: str) -> dict:
    """Запись отчёта о найденном дубликате."""
    return {"id": str(task.get("id", "")),
            "title": str(task.get("title", "")), "method": method}
