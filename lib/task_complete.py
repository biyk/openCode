"""Голосовая команда «завершил задачу {название}» (эквивалент ⏹/✅).

Название пустое — завершается запущенная сейчас задача (start_date != 0,
эквивалент ⏹/stop.md, длительность по факту). Название названо — по нему
находится сегодняшнее мероприятие (как в lib.task_start), uuid берётся из
описания; далее по состоянию строки: запущена/на паузе (start≠0 или
накопленный task_finish_date≠0) → ⏹ (факт), не начиналась →
✅ (done.md, по плану). Название чистится от слов-паразитов и ищется
нечётко (порог в TaskStartHandler).

Запуск:
    python -m lib.task_complete "название задачи"
    python -m lib.task_complete            # без названия → запущенная
"""

import sys
from datetime import datetime
from typing import Any, Optional

from lib.core.errors import swallowed
from lib.google_calendar import GoogleCalendar
from lib.google.google_calendar_mutate import DONE_COLOR
from lib.sleep_event import SLEEP_TITLE_RE
from lib.task_start import TaskStartHandler
from lib.taskflow.cells import as_int
from lib.taskflow.done_task import mark_task_done
from lib.taskflow.real_life_sheet import COLS, RealLifeSheet
from lib.taskflow.stop_task import stop_task

# Озвучка завершения: похвала + следующая задача (клиент говорит сам, как в
# lib.plans/lib.shopping — голосовой цикл ничего не добавляет).
# Фраза собрана БЛОКАМИ: неизменные фреймы («Задача выполнена.», «Вы
# умничка!», «Следующая задача:») — свой блок (кэшируются один раз на все
# задачи навсегда), название задачи — отдельный блок (кэш по названию).
# Так ежедневные фреймы не генерятся заново, а новое название синтезируется
# во время проговаривания уже готового фрейма (speak_blocks).
DONE_FRAME = "Задача выполнена."
DONE_PRAISE = "Вы умничка!"
NEXT_FRAME = "Следующая задача:"


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
        # «В работе» = запущена (G≠0) ИЛИ на паузе (накоплен O≠0). Пауза —
        # не завершение: закрываем по факту (⏹), а не ✅ по плану (иначе
        # «уже засчитана сегодня» блокирует закрытие незавершённой задачи).
        in_progress = (as_int(row[COLS["start_date"]]) != 0
                       or as_int(row[COLS["task_finish_date"]]) != 0)
        if in_progress:
            result = stop_task(task_uuid, api=self.api, now=self.now)
        else:
            result = mark_task_done(task_uuid, api=self.api, now=self.now)
        result["branch"] = "⏹" if in_progress else "✅"
        result.setdefault("title", info)
        result["uuid"] = task_uuid
        return result

    def next_task(self, done_uuid: Optional[str] = None) -> Optional[dict]:
        """Ближайшее незакрытое мероприятие после сейчас (кроме сделанного).

        list_events отдаёт будущие события, уже отсортированные по началу;
        отбрасываем выполненные (colorId=DONE_COLOR), «СОН» и только что
        закрытую задачу — остаётся то, что делать следующим.
        """
        try:
            events = self.gcal.list_events(limit=50)
        except Exception as e:  # нет токена/сети — озвучка без «следующей»
            swallowed("task_complete.next", e)
            return None
        for ev in events:
            if str(ev.get("colorId") or "").strip() == DONE_COLOR:
                continue
            if done_uuid and done_uuid in str(ev.get("description") or ""):
                continue
            summary = str(ev.get("summary") or "").strip()
            if not summary or SLEEP_TITLE_RE.search(summary):
                continue
            return ev
        return None


def _celebrate(handler: TaskCompleteHandler, result: dict) -> list[str]:
    """Блоки озвучки: похвала за сделанную задачу + что следующее.

    Неизменный фрейм и название — РАЗНЫЕ блоки: фрейм попадёт в кэш и
    заиграет мгновенно, название (новое/редкое) сгенерится за его спиной.
    """
    blocks = [DONE_FRAME]
    title = str(result.get("title") or "").strip()
    if title:
        blocks.append(f"{title}.")
    blocks.append(DONE_PRAISE)
    nxt = handler.next_task(result.get("uuid"))
    if nxt:
        next_title = str(nxt.get("summary") or "").strip()
        if next_title:
            blocks += [NEXT_FRAME, f"{next_title}."]
    return blocks


def _speak(blocks: list[str]) -> None:
    """Озвучить блоки; TTS лениво (как в shopping), сбой — в лог."""
    from lib.tts import TextToSpeech
    try:
        TextToSpeech().speak_blocks(blocks)
    except Exception as e:
        print("[Voice] Озвучка не удалась:", e)


def _main(argv: Optional[list[str]] = None) -> int:
    """CLI: `python -m lib.task_complete ["название задачи"]`. 0 — успех."""
    name = " ".join(sys.argv[1:] if argv is None else argv).strip()
    handler = TaskCompleteHandler()
    try:
        result = handler.complete_task(name)
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
    blocks = _celebrate(handler, result)
    print(" ".join(blocks))
    _speak(blocks)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
