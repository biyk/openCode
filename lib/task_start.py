"""Голосовая команда «я начал / я приступил {задача}» (эквивалент ▶️).

Находит в мероприятиях НА СЕГОДНЯ задачу по названию, берёт из её
описания task_uuid, ищет строку в Google Таблице real_life_tasks и
старует задачу: пишет start_date (колонка G) = now_ms − накопленная
длительность паузы (колонка O). Меняется ровно одна ячейка; журнал,
герой и календарь не трогаются (см. doit.md §0, §3, §10).

Запуск:
    python -m lib.task_start "название задачи"
"""

import re
import sys
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Callable, Optional

from lib.core.tuning import (
    EVENT_MATCH_DEBUG_TOP, TITLE_THRESHOLD, TOKEN_RATIO, TOKEN_ROOT_PREFIX)
from lib.google_calendar import GoogleCalendar
from lib.taskflow.task_start_sheet import TaskStartSheet

# UUID в описании события-задачи (колонка D листа = стабилизатор Sheet↔Calendar)
UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE)
# Слова-паразиты перед названием задачи в речи («я начал задачу починить…»)
NOISE_WORDS = {"задача", "задачу", "мероприятие", "дело", "к"}
# Порог похожести названия и правила «одно ли слово» — в lib.core.tuning
# (TITLE_THRESHOLD, TOKEN_ROOT_PREFIX, TOKEN_RATIO).
# Местоимения/связки — не значимые слова для матчинга мероприятия
# («я почистил зубы» → ядро «почистил зубы»). Не путать с NOISE_WORDS:
# те срезаются только в начале, эти игнорируются по всему тексту.
_STOP_TOKENS = {"я", "ты", "мы", "он", "она", "оно", "вы", "они",
                "мне", "меня", "мной", "моё", "мое", "мой", "моя",
                "это", "то", "и", "в", "на", "с", "у", "да"}


def _norm(text: str) -> str:
    """Нормализация названия: нижний регистр, ё→е, без пунктуации."""
    text = " ".join(text.lower().replace("ё", "е").split())
    return "".join(ch for ch in text if ch.isalnum() or ch == " ").strip()


def _content_tokens(norm: str) -> list[str]:
    """Значимые слова нормализованной строки (без местоимений/связок)."""
    return [t for t in norm.split() if t and t not in _STOP_TOKENS]


def _same_word(a: str, b: str) -> bool:
    """Одно ли слово: точно, по общему корню или по похожести (падеж/вид)."""
    if a == b:
        return True
    if (min(len(a), len(b)) >= TOKEN_ROOT_PREFIX
            and a[:TOKEN_ROOT_PREFIX] == b[:TOKEN_ROOT_PREFIX]):
        return True
    return SequenceMatcher(None, a, b).ratio() >= TOKEN_RATIO


def _overlap_score(target: str, title: str) -> float:
    """Похожесть по составу слов (Дайс): устойчива к падежу/виду и лишним
    словам («утро»/«вечер»), где SequenceMatcher по строке недодаёт."""
    tt = _content_tokens(target)
    ct = _content_tokens(title)
    if not tt or not ct:
        return 0.0
    matched = sum(1 for w in ct if any(_same_word(t, w) for t in tt))
    return 2 * matched / (len(tt) + len(ct))


class TaskStartHandler:
    """Старт задачи по голосовому названию через календарь и таблицу."""

    def __init__(self, gcal: Any = None, sheet: Any = None,
                 now: Optional[datetime] = None) -> None:
        self.gcal = gcal or GoogleCalendar()
        self.sheet = sheet or TaskStartSheet(self.gcal)
        self.now = now or datetime.now().astimezone()

    def _today_events(self) -> list[dict]:
        """Список мероприятий сегодня (от полуночи до полуночи)."""
        day_start = self.now.replace(hour=0, minute=0, second=0,
                                     microsecond=0)
        return self.gcal.list_events_between(
            day_start, day_start + timedelta(days=1))

    def find_task_event(self, name: str,
                        filter_fn: Optional[Callable[[dict], bool]] = None,
                        report: Optional[Callable[[str, float], None]] = None,
                        ) -> Optional[dict]:
        """Мероприятие сегодня с наиболее близким названием (или None).

        Название-подстрока фразы (Laya отдаёт всю фразу без команды)
        считается полным совпадением; при нескольких таких — берётся
        самое длинное название. filter_fn — необязательный предикат:
        событие, для которого он False, пропускается (напр. выполненное
        с colorId=7 не участвует в поиске). report(summary, score) —
        отладочный прогон лучших кандидатов (см. EVENT_MATCH_DEBUG_TOP).
        """
        target = _norm(self._strip_noise(name))
        if not target:
            return None
        best: Optional[tuple[tuple[float, int], dict]] = None
        scored: list[tuple[float, str]] = []
        for ev in self._today_events():
            if filter_fn is not None and not filter_fn(ev):
                continue
            title = _norm(ev.get("summary") or "")
            if not title:
                continue
            summary = ev.get("summary") or ""
            if title == target:
                if report is not None:
                    report(summary, 1.0)
                return ev
            if f" {title} " in f" {target} ":
                score = 1.0
            else:
                score = max(SequenceMatcher(None, target, title).ratio(),
                            _overlap_score(target, title))
            scored.append((score, summary))
            key = (score, len(title))
            if best is None or key > best[0]:
                best = (key, ev)
        if report is not None:
            for score, summary in sorted(scored, reverse=True)[
                    :EVENT_MATCH_DEBUG_TOP]:
                report(summary, score)
        if best is not None and best[0][0] >= TITLE_THRESHOLD:
            return best[1]
        return None

    @staticmethod
    def _strip_noise(name: str) -> str:
        """Убирает ведущее слово-паразит («задачу помыть пол» → «помыть пол»)."""
        tokens = name.split()
        while tokens and tokens[0].lower().replace("ё", "е") in NOISE_WORDS:
            tokens = tokens[1:]
        return " ".join(tokens)

    @staticmethod
    def event_uuid(event: dict) -> Optional[str]:
        """task_uuid из описания мероприятия (или None)."""
        match = UUID_RE.search(event.get("description") or "")
        return match.group(0).lower() if match else None

    def start_task(self, name: str) -> dict:
        """Эквивалент клика ▶️: одна запись G у строки с uuid задачи."""
        event = self.find_task_event(name)
        if event is None:
            return {"ok": False, "error": f"задача «{name}» не найдена "
                    f"среди мероприятий на сегодня"}
        task_uuid = self.event_uuid(event)
        if task_uuid is None:
            return {"ok": False,
                    "error": f"в описании «{event['summary']}» нет uuid"}
        row = self.sheet.find_row_by_uuid(task_uuid)
        if row is None:
            return {"ok": False,
                    "error": f"строка {task_uuid} не найдена в таблице"}
        current_start, finish = self.sheet.read_start_finish(row)
        if current_start != 0:
            return {"ok": False,
                    "error": f"задача «{event['summary']}» уже запущена"}
        now_ms = int(self.now.timestamp() * 1000)
        new_start = now_ms - finish          # finish == 0 → просто now
        self.sheet.write_start(row, new_start)
        return {"ok": True, "title": event["summary"], "uuid": task_uuid,
                "row": row, "new_start": new_start}


def _main(argv: Optional[list[str]] = None) -> int:
    """CLI: `python -m lib.task_start "название задачи"`. 0 — успех."""
    name = " ".join(sys.argv[1:] if argv is None else argv).strip()
    if not name:
        print("Укажите название задачи: python -m lib.task_start \"...\"")
        return 1
    result = TaskStartHandler().start_task(name)
    if result.get("ok"):
        print(f"▶️ Задача «{result['title']}» запущена "
              f"(строка {result['row']}, start={result['new_start']})")
        return 0
    print(f"❌ {result['error']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
