# TOOLTIP: Закрывает дыры календаря развлечениями и списывает hero_money
"""Один проход: найденные дыры (fun_holes) → события-развлечения → списание.

За каждую дыру вставляется событие `FUN_EVENT_TITLE` («Отдых») с длительностью
всей дыры, hero_money уменьшается на число её минут (1 минута = 1 hero_money,
минус разрешён), а в rewards_history идёт строка покупки награды
`FUN_REWARD_TITLE` — её reward_id и заголовок живут именно в журнале.
Озвучки нет по решению пользователя — факт виден в календаре и в таблице.

Вызывается каждый цикл фонового контроля задач (`make_fun_fill` подключается в
task_monitor) и вручную: `python -m lib.taskflow.fun_fill [--dry]`.

Озвучки нет, поэтому каждое реальное действие ещё и пишется в аудит-файл
`logs/fun_holes.log` (JSONL): сама дыра, сколько списано hero_money, id
созданного события и id строки в rewards_history.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from lib.core.errors import swallowed
from lib.core.tuning import (FUN_EVENT_TITLE, FUN_LOOKBACK_DAYS,
                             FUN_MIN_GAP_MIN, FUN_REWARD_TITLE)
from lib.google_calendar import GoogleCalendar
from lib.taskflow.fun_holes import FUN_MARKER, find_holes, fun_color
from lib.taskflow.rewards_sheet import RewardsSheet

EVENTS_LIMIT = 500            # событий за окно lookback (с запасом на неделю)
PREFIX = "[FunHoles]"
AUDIT_PATH = Path("logs") / "fun_holes.log"   # JSONL действий по дырам


def _audit(entry: dict) -> None:
    """Одна строка аудита: дыра, деньги, id события и строки журнала.

    Фоновый проход молчит (озвучки по решению пользователя нет), поэтому
    разбираться, что произошло с дырой и балансом, придётся по этому файлу.
    Сбой записи наружу не пускаем: аудит не должен ломать заполнение дыр.
    """
    line = json.dumps({"at": datetime.now().isoformat(timespec="seconds"),
                       **entry}, ensure_ascii=False, default=str)
    try:
        AUDIT_PATH.parent.mkdir(exist_ok=True)
        with open(AUDIT_PATH, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as error:
        swallowed("fun_holes.audit", error)


def _info(output: Any, message: str) -> None:
    """Строчка в лог приложения; в CLI (output=None) — просто в консоль."""
    if output is not None:
        output.print_info(message)
        return
    try:
        print(message)
    except UnicodeEncodeError:
        # Консоль Windows в cp1251 не всякий символ переводит.
        print(message.encode("cp1251", "replace").decode("cp1251"))


def _fill_one(gcal: Any, sheet: Any, hole: dict, reward: dict,
              color: str, now: datetime, output: Any) -> bool:
    """Одна дыра → событие + списание. True — если и событие, и списание."""
    minutes = int(round(hole["minutes"]))
    base = {"action": "fill", "hole_start": hole["start"].isoformat(),
            "hole_end": hole["end"].isoformat(),
            "hole_minutes": round(float(hole["minutes"]), 1),
            "gold_spent": minutes, "event_title": FUN_EVENT_TITLE,
            "color_id": color, "reward_title": reward["title"],
            "reward_id": reward["reward_id"]}
    event_id = gcal.create_task_event(
        FUN_EVENT_TITLE, FUN_MARKER, hole["start"], hole["end"],
        color_id=color)
    if not event_id:
        _info(output, f"{PREFIX} {hole['start']:%H:%M}: событие не создано")
        _audit({**base, "event_id": None, "claim_item_id": None,
                "ok": False, "error": "событие не создано"})
        return False
    try:
        claim_id = sheet.spend(reward, minutes, now)
    except Exception as error:                # деньги не списаны — журнал решит
        _audit({**base, "event_id": event_id, "claim_item_id": None,
                "ok": False, "error": f"списание: {error}"})
        return swallowed("fun_holes.spend", error, False)
    _audit({**base, "event_id": event_id, "claim_item_id": str(claim_id),
            "ok": True})
    _info(output, f"{PREFIX} {hole['start']:%H:%M}–{hole['end']:%H:%M} "
                  f"«{FUN_EVENT_TITLE}» -{minutes} hero_money")
    return True


def fill(gcal: Any, sheet: Any, output: Any = None,
         now: Optional[datetime] = None, dry: bool = False,
         min_gap: float = FUN_MIN_GAP_MIN,
         lookback: int = FUN_LOOKBACK_DAYS) -> int:
    """Заполняет сегодняшние дыры; возвращает число созданных событий."""
    now = now or datetime.now().astimezone()
    events = gcal.list_events_between(
        now - timedelta(days=lookback), now, limit=EVENTS_LIMIT)
    holes = find_holes(events, now, min_gap)
    if not holes:
        _info(output, f"{PREFIX} Дыр между синими задачами нет")
        return 0
    if dry:
        for hole in holes:
            _info(output, f"{PREFIX} дыра {hole['start']:%H:%M}–"
                          f"{hole['end']:%H:%M} = {hole['minutes']:.1f} мин")
        return len(holes)
    reward = sheet.find_reward(FUN_REWARD_TITLE)
    if reward is None:
        # Без награды не знаем ни reward_id, ни заголовок — не и списываем.
        _info(output, f"{PREFIX} награды «{FUN_REWARD_TITLE}» "
                      f"нет в real_life_rewards, пропускаем")
        _audit({"action": "skip_no_reward", "holes_found": len(holes),
                "reward_title": FUN_REWARD_TITLE, "ok": False})
        return 0
    color = fun_color(events)
    done = 0
    spent = 0
    for hole in holes:
        if _fill_one(gcal, sheet, hole, reward, color, now, output):
            done += 1
            spent += int(round(hole["minutes"]))
    _audit({"action": "run", "holes_found": len(holes), "filled": done,
            "gold_spent_total": spent, "min_gap_min": min_gap,
            "lookback_days": lookback})
    return done


def make_fun_fill(output: Any, min_gap: float = FUN_MIN_GAP_MIN,
                  lookback: int = FUN_LOOKBACK_DAYS) -> Callable[[], None]:
    """Замыкание для task_monitor: ленивые клиенты, сбой — только в лог."""
    clients: dict[str, Any] = {}

    def run() -> None:
        try:
            if not clients:
                clients["gcal"] = GoogleCalendar()
                clients["sheet"] = RewardsSheet(clients["gcal"])
            fill(clients["gcal"], clients["sheet"], output=output,
                 min_gap=min_gap, lookback=lookback)
        except Exception as error:            # цикл монитора живёт дальше
            swallowed("fun_holes.tick", error)

    return run


def _main(argv: Optional[list[str]] = None) -> int:
    """CLI: `python -m lib.taskflow.fun_fill [--dry]`."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="python -m lib.taskflow.fun_fill",
        description="Заполнить дыры календаря развлечениями")
    parser.add_argument("--dry", action="store_true",
                        help="только показать найденные дыры")
    args = parser.parse_args(argv)
    gcal = GoogleCalendar()
    count = fill(gcal, RewardsSheet(gcal), dry=args.dry)
    print(f"развлечений создано: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
