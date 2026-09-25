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
from typing import Any, Optional

from lib.google_calendar import GoogleCalendar
from lib.task_start_sheet import TaskStartSheet

# UUID в описании события-задачи (колонка D листа = стабилизатор Sheet↔Calendar)
UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE)
# Слова-паразиты перед названием задачи в речи («я начал задачу починить…»)
NOISE_WORDS = {"задача", "задачу", "мероприятие", "дело", "к"}
# Порог похожести названия: ниже — не угадываем (концепция уровня 1)
TITLE_THRESHOLD = 0.75


def _norm(text: str) -> str:
    """Нормализация названия: нижний регистр, ё→е, без пунктуации."""
    text = " ".join(text.lower().replace("ё", "е").split())
    return "".join(ch for ch in text if ch.isalnum() or ch == " ").strip()


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

    def find_task_event(self, name: str) -> Optional[dict]:
        """Мероприятие сегодня с наиболее близким названием (или None).

        Название-подстрока фразы (Laya отдаёт всю фразу без команды)
        считается полным совпадением; при нескольких таких — берётся
        самое длинное название.
        """
        target = _norm(self._strip_noise(name))
        if not target:
            return None
        best: Optional[tuple[tuple[float, int], dict]] = None
        for ev in self._today_events():
            title = _norm(ev.get("summary") or "")
            if not title:
                continue
            if title == target:
                return ev
            if f" {title} " in f" {target} ":
                score = 1.0
            else:
                score = SequenceMatcher(None, target, title).ratio()
            key = (score, len(title))
            if best is None or key > best[0]:
                best = (key, ev)
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
