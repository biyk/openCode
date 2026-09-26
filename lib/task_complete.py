"""Голосовая команда «завершил задачу {название}» (эквивалент ⏹/✅).

Название пустое — завершается запущенная сейчас задача (start_date != 0,
эквивалент ⏹/stop.md, длительность по факту). Название названо — по нему
находится сегодняшнее мероприятие (как в lib.task_start), uuid берётся из
описания; далее по состоянию строки: запущена → ⏹ (факт), не запущена →
✅ (done.md, по плану). Название чистится от слов-паразитов и ищется
нечётко (порог в TaskStartHandler).

Запуск:
    python -m lib.task_complete "название задачи"
    python -m lib.task_complete            # без названия → запущенная
"""

import sys
from datetime import datetime
from typing import Any, Optional

from lib.google_calendar import GoogleCalendar
from lib.task_start import TaskStartHandler
from lib.taskflow.cells import as_int
from lib.taskflow.done_task import mark_task_done
from lib.taskflow.real_life_sheet import COLS, RealLifeSheet
from lib.taskflow.stop_task import stop_task


class TaskCompleteHandler:
    """Завершение задачи: по названию или текущей запущенной."""

    def __init__(self, gcal: Any = None, api: Any = None,
                 now: Optional[datetime] = None) -> None:
        self.now = now or datetime.now().astimezone()
        self.gcal = gcal or GoogleCalendar()
        self.api = api or RealLifeSheet(self.gcal)
        self._finder = TaskStartHandler(gcal=self.gcal, now=self.now)

    def resolve_uuid(self, name: str) -> tuple[Optional[str], str]:
        """(uuid, title) задачи; uuid None → title содержит текст ошибки.

        Пустое название — берём запущенную задачу из таблицы; названное —
        ищем сегодняшнее мероприятие по имени (переиспользуя TaskStart).
        """
        name = (name or "").strip()
        if not name:
            running = self.api.find_running_task()
            if running is None:
                return None, "нет запущенной задачи"
            return running["uuid"], running["title"]
        event = self._finder.find_task_event(name)
        if event is None:
            return None, (f"задача «{name}» не найдена среди мероприятий "
                          "на сегодня")
        task_uuid = self._finder.event_uuid(event)
        if task_uuid is None:
            return None, f"в описании «{event['summary']}» нет uuid"
        return task_uuid, str(event["summary"]).strip()

    def complete_task(self, name: str) -> dict:
        """Эквивалент ⏹/✅: ветвь выбирается по start_date строки."""
        task_uuid, info = self.resolve_uuid(name)
        if task_uuid is None:
            return {"ok": False, "error": info}
        found = self.api.find_task_row(task_uuid)
        if found is None:
            return {"ok": False,
                    "error": f"строка {task_uuid} не найдена в таблице"}
        row = found[1]
        running = as_int(row[COLS["start_date"]]) != 0
        if running:
            result = stop_task(task_uuid, api=self.api, now=self.now)
        else:
            result = mark_task_done(task_uuid, api=self.api, now=self.now)
        result["branch"] = "⏹" if running else "✅"
        result.setdefault("title", info)
        return result


def _main(argv: Optional[list[str]] = None) -> int:
    """CLI: `python -m lib.task_complete ["название задачи"]`. 0 — успех."""
    name = " ".join(sys.argv[1:] if argv is None else argv).strip()
    try:
        result = TaskCompleteHandler().complete_task(name)
    except Exception as e:  # нет токена/сети/неизвестный repeat_mode
        print(f"[complete] ошибка завершения: {e}")
        return 1
    if result.get("skipped"):
        print(f"[complete] «{result['title']}» уже засчитана сегодня")
        return 0
    if not result.get("ok"):
        print(f"[complete] {result['error']}")
        return 1
    if result.get("branch") == "⏹":
        print(f"⏹ «{result['title']}» завершена по факту: "
              f"{result['elapsed_minutes']} мин, "
              f"награда {result['money']:.2f}")
    else:
        print(f"✅ «{result['title']}» засчитана по плану: "
              f"{result['time_spent']} мин, награда {result['money']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
