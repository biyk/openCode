"""Голосовая команда «я проснулся»: фиксирует конец события «СОН» в календаре.

Ищет в Google Calendar ближайшее мероприятие с названием «СОН», которое
НАЧАЛОСЬ до момента произнесения команды (т.е. сон, от которого
проснулись), и меняет ему только дату завершения на текущий момент
(время начала не трогает). Т.е. команда отмечает, во сколько сон
реально закончился.

Дополнительно команда засчитывает по ✅ задачу «Пробуждение» из
JS-приложения (done.md): галочка в календаре, строка real_life_tasks,
журнал task_executions и награда героя. Засчёт не блокирует фиксацию
пробуждения: при его ошибке команда печатает предупреждение.

CLI: `python -m lib.wake_event`. Коды выхода: 0 — конец зафиксирован
(или хотя бы засчитана задача), 1 — событие не найдено и задача не
засчитана / запрос к Google не прошёл.
"""

from datetime import datetime, timedelta
from typing import Optional

from lib.google_calendar import GoogleCalendar
from lib.google.google_calendar_events import GoogleCalendarEventsMixin
from lib.sleep_event import SLEEP_TITLE_RE
from lib.taskflow.done_task import mark_task_done

# Сон, от которого просыпаются, начался не дальше суток назад.
LOOKBACK = timedelta(hours=24)
# Небольшой зазор в будущее: «началось до момента» округляем по now.
LOOKAHEAD = timedelta(hours=1)
# Задача «Пробуждение» в real_life_tasks (её uuid) — засчитывается ✅.
WAKE_TASK_UUID = "f29ef6e3-f1f9-418c-a657-49ffa5dc9497"


class WakeEventHandler:
    """Находит начавшийся «СОН» и переносит его конец на текущий момент."""

    def __init__(self, google: Optional[GoogleCalendar] = None,
                 now: Optional[datetime] = None) -> None:
        self._google = google or GoogleCalendar()
        self._now = now

    @property
    def now(self) -> datetime:
        """Текущее время (для тестов — фиксированное)."""
        return self._now if self._now is not None else datetime.now().astimezone()

    def find_started_sleep_event(self) -> Optional[dict]:
        """«СОН», начавшийся раньше всего недавнего момента.

        Среди событий с названием «СОН», начало которых строго до
        текущего времени, берётся самое позднее по началу — то, от
        которого проснулись сейчас.
        """
        events = self._google.list_events_between(
            self.now - LOOKBACK, self.now + LOOKAHEAD)
        now = self.now
        candidates = []
        for ev in events:
            if not SLEEP_TITLE_RE.search(ev.get("summary") or ""):
                continue
            start = GoogleCalendarEventsMixin._parse_event_datetime(
                ev.get("start"))
            if start is None:
                continue
            if start.tzinfo is None:
                start = start.astimezone()
            if start >= now:
                continue  # ещё не началось
            candidates.append((start, ev))
        if not candidates:
            return None
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return candidates[0][1]

    def fix_wake_end(self) -> Optional[dict]:
        """Меняет конец «СНА» на сейчас (начало не трогает).

        None — если не удалось.
        """
        ev = self.find_started_sleep_event()
        if ev is None:
            return None
        if not self._google.update_event_end(ev["id"], self.now):
            return None
        ev["end"] = self.now.isoformat()
        return ev


def count_wake_task(now: datetime) -> bool:
    """✅ по задаче «Пробуждение»: True — если засчитана (или уже была).

    Ошибки Google не останавливают команду — печать сообщения о них.
    """
    try:
        result = mark_task_done(WAKE_TASK_UUID, now=now)
    except Exception as e:  # нет токена/сети/задача запущена (ожидается ⏹)
        print(f"[wake] «Пробуждение» не засчитано: {e}")
        return False
    if not result.get("ok"):
        print(f"[wake] «Пробуждение» не засчитано: {result.get('error')}")
        return False
    if result.get("skipped"):
        print(f"[wake] «{result['title']}» уже засчитана сегодня")
    else:
        print(f"[wake] ✅ «{result['title']}» засчитана по плану: "
              f"{result['time_spent']} мин, награда {result['money']:.2f}")
    return True


def _main(argv: Optional[list[str]] = None) -> int:
    handler = WakeEventHandler()
    try:
        ev = handler.fix_wake_end()
    except Exception as e:  # нет токена/сети — сообщаем и падаем
        print(f"[wake] ошибка календаря: {e}")
        return 1
    counted = count_wake_task(handler.now)
    if ev is None:
        print("[wake] начавшееся событие «СОН» не найдено")
        return 0 if counted else 1
    print(f"[wake] конец «{ev['summary']}» перенесён на "
          f"{handler.now:%d.%m.%Y %H:%M}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
