"""Совпадение названия товара с позициями списка: дубликаты и поиск на удаление.

Дубликаты (проверка ПЕРЕД добавлением) выключены: `shopping.dedup.enabled`
в commands.json стоит false — товар добавляется как есть. Механизм
готов и обкатан тестами, чтобы включить его позже одним флагом:
`enabled` — точное совпадение, `fuzzy` — плюс нечёткое (SequenceMatcher
не ниже `threshold`).

Поиск на удаление («купил X») работает всегда и шире: точное совпадение →
подстрока (в таблице «Молоко 2л», сказано «молоко») → нечёткое, только
если `fuzzy` разрешён конфигом. Без него команда «купил» не нашла бы
строку из-за регистра или падежа.

Нормализация общая: нижний регистр, ё→е, пунктуация в пробелы, пробелы
в один. Поэтому «Молоко, 2 литра» и «молоко 2 литра» — одна позиция.
"""

import re
from difflib import SequenceMatcher
from typing import Optional

# Порог нечёткого совпадения по умолчанию: ниже — разные товары.
DEFAULT_THRESHOLD = 0.9

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Название к единому виду для сравнения (регистр, ё/е, пунктуация)."""
    text = (text or "").lower().replace("ё", "е")
    text = _PUNCT_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def dedup_enabled(config: Optional[dict]) -> bool:
    """Включён ли поиск дубликатов (shopping.dedup.enabled)."""
    return bool((config or {}).get("enabled"))


def fuzzy_enabled(config: Optional[dict]) -> bool:
    """Разрешено ли нечёткое сравнение (shopping.dedup.fuzzy)."""
    cfg = config or {}
    return dedup_enabled(cfg) and bool(cfg.get("fuzzy"))


def threshold(config: Optional[dict]) -> float:
    """Порог нечёткого совпадения из конфига (DEFAULT_THRESHOLD по умолчанию)."""
    try:
        value = float((config or {}).get("threshold") or DEFAULT_THRESHOLD)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD
    return value if 0.0 < value <= 1.0 else DEFAULT_THRESHOLD


def find_duplicate(name: str, existing: list[dict],
                   config: Optional[dict] = None) -> Optional[dict]:
    """Дубликат среди existing ({"row", "name"}) перед добавлением.

    Возвращает {"row", "name", "method", "score"?} (method: exact|fuzzy)
    или None. Выключенный dedup (см. докстринг модуля) — всегда None,
    то есть добавление не блокируется.
    """
    if not dedup_enabled(config):
        return None
    query = normalize(name)
    if not query:
        return None
    hit = _exact(query, existing)
    if hit is not None:
        return hit
    if fuzzy_enabled(config):
        return _fuzzy(query, existing, threshold(config))
    return None


def find_item(name: str, existing: list[dict],
              config: Optional[dict] = None) -> Optional[dict]:
    """Позиция списка, которую имели в виду в фразе «купил {товар}».

    Точное совпадение → подстрока в любую сторону → нечёткое (только
    при включённом fuzzy). None — совпадения нет, удалять нечего.
    """
    query = normalize(name)
    if not query:
        return None
    hit = _exact(query, existing)
    if hit is not None:
        return hit
    hit = _contains(query, existing)
    if hit is not None:
        return hit
    if fuzzy_enabled(config):
        return _fuzzy(query, existing, threshold(config))
    return None


def _hit(item: dict, method: str,
         score: Optional[float] = None) -> dict:
    """Отчёт о найденной позиции (score — уверенность нечёткого сравнения)."""
    found = {"row": item.get("row"), "name": str(item.get("name", "")),
             "method": method}
    if score is not None:
        found["score"] = round(score, 4)
    return found


def _exact(query: str, existing: list[dict]) -> Optional[dict]:
    """Первая позиция с тем же нормализованным названием."""
    for item in existing:
        if normalize(str(item.get("name", ""))) == query:
            return _hit(item, "exact")
    return None


def _contains(query: str, existing: list[dict]) -> Optional[dict]:
    """Позиция, чьё название содержит запрос (или наоборот).

    Берётся самое длинное название: «молоко» ближе к «молоко 2л», чем к
    «молоко» в другой строке с лишним словом.
    """
    best: Optional[tuple[int, dict]] = None
    for item in existing:
        name = normalize(str(item.get("name", "")))
        if not name:
            continue
        if query in name or name in query:
            if best is None or len(name) > best[0]:
                best = (len(name), item)
    return _hit(best[1], "contains") if best else None


def _fuzzy(query: str, existing: list[dict],
           limit: float) -> Optional[dict]:
    """Самое похожее название, если похожесть не ниже порога."""
    best: Optional[tuple[float, dict]] = None
    for item in existing:
        name = normalize(str(item.get("name", "")))
        if not name:
            continue
        score = SequenceMatcher(None, query, name).ratio()
        if best is None or score > best[0]:
            best = (score, item)
    if best is None or best[0] < limit:
        return None
    return _hit(best[1], "fuzzy", best[0])
