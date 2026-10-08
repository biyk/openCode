"""Чистые скоринги похожести фразы на заголовок мероприятия.

Вынесено из `lib/task_start.py` под лимит 200 строк. Никакого I/O: только
нормализация и SequenceMatcher/Дайс. `lib/task_start.py` импортирует
эти функции; тесты — в `tests/taskflow/test_task_start.py`.
"""

from difflib import SequenceMatcher

from lib.core.event_text import STOP_TOKENS, clean_title
from lib.core.tuning import TOKEN_RATIO, TOKEN_ROOT_PREFIX


def norm(text: str) -> str:
    """Нормализация: очистка (скобки/эмодзи), нижний регистр, ё→е, без пунктуации."""
    text = " ".join(clean_title(text).lower().replace("ё", "е").split())
    return "".join(ch for ch in text if ch.isalnum() or ch == " ").strip()


def content_tokens(n: str) -> list[str]:
    """Значимые слова нормализованной строки (без местоимений/связок)."""
    return [t for t in n.split() if t and t not in STOP_TOKENS]


def same_word(a: str, b: str) -> bool:
    """Одно ли слово: точно, по общему корню или по похожести (падеж/вид)."""
    if a == b:
        return True
    if (min(len(a), len(b)) >= TOKEN_ROOT_PREFIX
            and a[:TOKEN_ROOT_PREFIX] == b[:TOKEN_ROOT_PREFIX]):
        return True
    return SequenceMatcher(None, a, b).ratio() >= TOKEN_RATIO


def overlap_score(target: str, title: str) -> float:
    """Похожесть по составу слов (Дайс): устойчива к падежу/виду и лишним
    словам («утро»/«вечер»), где SequenceMatcher по строке недодаёт."""
    tt = content_tokens(target)
    ct = content_tokens(title)
    if not tt or not ct:
        return 0.0
    matched = sum(1 for w in ct if any(same_word(t, w) for t in tt))
    return 2 * matched / (len(tt) + len(ct))


def segment_score(target: str, seg: str) -> float:
    """Похожность одной точки составного заголовка на фразу-мишень."""
    if f" {seg} " in f" {target} ":
        return 1.0
    return max(SequenceMatcher(None, target, seg).ratio(),
               overlap_score(target, seg))
