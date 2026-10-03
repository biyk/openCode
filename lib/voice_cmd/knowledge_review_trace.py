# lib/voice_cmd/knowledge_review_trace.py
"""Локальные оценки и текстовый след распознавания на доске знаний.

Числа в следе считаются здесь, а не берутся у ИИ: match-шаблон commands.json
(тот же `_similarity` и тот же порог MATCH_THRESHOLD, что в рантайме) и
похожесть угаданного параметра на задачи таблицы (тот же скоринг, что у
EventMatch, порог TITLE_THRESHOLD). Поэтому «0.87 < 0.90» в логе — это ровно
то, что увидел бы рантайм на этой фразе.

Помимо оценок модуль умеет собирать сам след — строки вида
`уровень: вердикт (оценка >= порог) — принято`, чтобы прогон «распознать
все» можно было прочитать постфактум, включая причины, по которым следующий
уровень не спрашивали.
"""

from __future__ import annotations

from typing import Optional

from lib.core.errors import swallowed
from lib.core.tuning import TITLE_THRESHOLD
from lib.voice_cmd.commands_match import MATCH_THRESHOLD, _similarity

__all__ = ["MATCH_THRESHOLD", "TITLE_THRESHOLD", "Trace", "best_template",
           "key_of", "norm", "quote", "score_titles"]

# Поле метки уровня: «commands.json:» и «LLM Race(omni+lmstudio):» разной
# длины, а колонки чисел должны стоять друг под другом — иначе лог в <pre>
# читается лесенкой.
LABEL_W = 25


def norm(text: str) -> str:
    """Нормализация фразы для сверки: нижний регистр, ё→е, один пробел."""
    return " ".join(str(text or "").lower().replace("ё", "е").split())


def quote(text: str) -> str:
    """Кавычки для значения в логе; пустое — как «—», чтобы бросалось в глаза.

    Кавычки обычные, не «ёлочки»: строка `ключ "..."` в фазе 1 печатается
    так же, и итог обязан читаться с ней в одном стиле.
    """
    return f'"{text}"' if text else "—"


def best_template(match: dict, text: str) -> tuple[str, str, float]:
    """Лучший match-кандидат (id, шаблон, оценка) БЕЗ порога — виден промах.

    Рантаймный `_match_command` ниже MATCH_THRESHOLD отдаёт (None, 0.0): для
    выполнения это верно, для следа теряется причина («0.87 < 0.9» вместо
    «ничего похожего»). Здесь тот же перебор префиксов и та же оценка.
    """
    tokens = norm(text).split()
    best: tuple[str, str, float] = ("", "", 0.0)
    if not tokens:
        return best
    for cid, templates in (match or {}).items():
        for tpl in templates or []:
            n = len(norm(tpl).split())
            if n == 0 or n > len(tokens):
                continue
            score = _similarity(" ".join(tokens[:n]), tpl)
            if score > best[2]:
                best = (cid, tpl, score)
    return best


def key_of(match: dict, cid: str, text: str) -> str:
    """Ключ команды, реально стоящий во фразе (для подписи в следе).

    Если во фразе сидят несколько шаблонов одной команды, берётся САМЫЙ
    длинный — так же, как рантайм при равных оценках предпочитает более
    длинный шаблон (`_match_command`, tie-break по числу слов).
    """
    phrase = norm(text)
    best = ""
    for tpl in (match or {}).get(cid, []) or []:
        t = norm(tpl)
        if t and len(t) > len(best) and f" {t} " in f" {phrase} ":
            best = t
    return best


def score_titles(text: str, titles: list[str]) -> tuple[str, float]:
    """Похожесть параметра на задачи таблицы: (задача, оценка).

    Скоринг заимствован у EventMatch (`_segment_score`, составные заголовки
    по точкам), поэтому число сравнимо с рантаймом. Пустой список (Sheets
    недоступен) или сбой импорта — ("", 0.0): оценки нет, прогон не падает.
    """
    try:
        from lib.core.event_text import strip_noise, title_segments
        from lib.task_start import _norm, _segment_score
    except Exception as e:
        swallowed("review.trace_scoring", e)
        return "", 0.0
    target = _norm(strip_noise(text))
    if not target:
        return "", 0.0
    best: tuple[str, float] = ("", 0.0)
    for title in titles or []:
        segs = [s for s in (_norm(x) for x in title_segments(title)) if s]
        if not segs:
            continue
        if target in segs:
            return title, 1.0
        score = max(_segment_score(target, seg) for seg in segs)
        if score > best[1]:
            best = (title, score)
    return best


class Trace:
    """Текстовый след распознавания одной фразы (строки с отступом)."""

    def __init__(self, text: str) -> None:
        self.lines: list[str] = [f"фраза:\t{text}"]

    def phase(self, title: str) -> None:
        """Заголовок фазы: «фаза 1\tопределение команды»."""
        self.lines.append(f"фаза {title}")

    def note(self, text: str) -> None:
        """Пояснение фазы (что именно ищем и где)."""
        self.lines.append(f"  {text}")

    def _col(self, label: str) -> str:
        """Метка уровня в поле фиксированной ширины + таб на границу колонок."""
        return f"{label:<{LABEL_W}}\t"

    def level(self, level: str, value: str, score: Optional[float],
              threshold: Optional[float], accepted: bool,
              tail: str = "") -> None:
        """Строка уровня: вердикт, оценка против порога, причина/ключ."""
        got = value or "—"
        if score is None or threshold is None:
            num = ""
        else:
            op = ">=" if score + 1e-09 >= threshold else "<"
            num = f" ({score:.2f} {op} {threshold:.2f})"
        end = " — фаза завершена" if accepted else " — не принято"
        extra = f" {tail}" if tail else ""
        self.lines.append(f"{self._col(level + ':')}{got}{num}{extra}{end}")

    def skipped(self, level: str, why: str) -> None:
        """Уровень не опрашивался — и обязательно почему."""
        self.lines.append(f"{self._col(level + ':')}"
                          f"пропущено, причина ({why})")

    def result(self, command: str, key: str, param: str) -> None:
        """Итог фразы."""
        self.lines.append(f"итог:\tкоманда {command or '—'} "
                          f"ключ {quote(key)} параметры {quote(param)}")

    def text(self) -> str:
        """След одной фразы (без завершающего перевода строки)."""
        return "\n".join(self.lines)


def run_header(stamp: str, total: int, recognized: int) -> str:
    """Шапка журнала прогона."""
    return (f"=== прогон {stamp}: фраз {total}, "
            f"распознано {recognized} ===")
