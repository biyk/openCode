# TOOLTIP: Фоновый контроль таблицы задач: вопрос вслух и старт по ответу
"""Периодическая проверка real_life_tasks (раз в TASK_MONITOR_INTERVAL_S).

Ни одной запущенной задачи (start_date = 0 у всех строк) — вслух вопрос
«чем ты сейчас занимаешься?»; следующая строка — ответ: название ищется
среди задач таблицы и найденная задача запускается (как `taskstart`).

Вопрос и сбор ответа — через оркестратор (`ask` из orchestrator_ask), чтобы
реплика пользователя не ушла в пайплайн команд. Живёт проверка в собственном
daemon-потоке (как version_checker): cron-подпроцесс не может ни озвучить
вопрос, ни поймать ответ. Собирает и запускает его `start_task_monitor`
(её вызывает main.py рядом с CronScheduler).
"""

import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from lib.core.errors import swallowed
from lib.core.overtime import OvertimeNotifier
from lib.core.rest_watch import RestWatch
from lib.core.task_pick import TASKSTART_CMD_ID
from lib.core.tuning import TASK_ANSWER_TIMEOUT_S, TASK_MONITOR_INTERVAL_S
from lib.task_start import TaskStartHandler
from lib.taskflow.real_life_sheet import RealLifeSheet
from lib.taskflow.task_check import evaluate
from lib.taskflow.task_schedule import idle_offer

# Вопрос, когда не запущено ничего (ответ — название задачи из таблицы).
QUESTION_IDLE = "Чем ты сейчас занимаешься?"
# К предложению незапущенной задачи в том же вопросе (см. suggest_idle_task).
PROPOSE_PREFIX = "Предлагаю задачу:"
# Ответ на него не похож ни на одну задачу: произносим и живём дальше.
ANSWER_UNKNOWN = "Такой задачи в списке нет"


class TaskMonitor:
    """Фоновый опрос таблицы задач и вопрос пользователю."""

    def __init__(self, ask: Callable[..., bool], say: Callable[[str], None],
                 output: Any, core: Optional[Callable[[str], str]] = None,
                 sheet: Any = None, handler: Any = None,
                 interval_s: float = TASK_MONITOR_INTERVAL_S,
                 answer_timeout_s: float = TASK_ANSWER_TIMEOUT_S,
                 fun: Optional[Callable[[], None]] = None,
                 overtime: Optional[OvertimeNotifier] = None,
                 title_fn: Optional[Callable[[], str]] = None,
                 classify_fn: Optional[Callable[[str], Any]] = None,
                 notify: Optional[Callable[[str], None]] = None,
                 gcal: Any = None,
                 offer: Optional[Callable[[str, list], None]] = None,
                 record: Optional[Callable[[str], None]] = None) -> None:
        self._ask = ask
        self._say = say
        self._output = output
        self._core = core or (lambda text: text)
        self._sheet = sheet
        self._handler = handler
        self._interval = interval_s
        self._answer_timeout_s = answer_timeout_s
        self._fun = fun
        self._overtime = overtime
        self._rest = RestWatch(title_fn, classify_fn, output)
        self._notify = notify
        self._gcal = gcal
        self._offer = offer
        self._record = record
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---------- Поток ----------

    def start(self) -> None:
        """Запускает daemon-поток; первая проверка — через интервал."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="task-monitor")
        self._thread.start()

    def stop(self) -> None:
        """Останавливает поток проверки."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.tick()
            except Exception as error:            # цикл не должен умирать
                swallowed("task_monitor.tick", error)

    # ---------- Одна проверка (публично для тестов) ----------

    def tick(self) -> str:
        """Читает таблицу; если запущено ничего нет — спрашивает вслух."""
        if self._fun is not None:
            self._fun()             # дыры календаря молча закрываются каждый цикл
        snapshot = self._snapshot()
        if snapshot is None:
            return "skip"
        check, rows = snapshot
        if self._overtime is not None:
            self._overtime.check(check)   # и при занятой задаче, не только idle
        if check.idle:
            self._rest.check_async()           # окно = отдых? проверить в фоне
            return self._handle_idle(rows)
        return "busy"

    def _handle_idle(self, rows: list) -> str:
        """Idle: голосовой вопрос с предложением + кнопка-оффер в Telegram."""
        voice, titles = self._offer_of(rows)
        question = (f"{QUESTION_IDLE} {PROPOSE_PREFIX} {voice}" if voice
                    else QUESTION_IDLE)
        if not self._ask(question, self._on_idle_answer, "task_idle",
                         self._answer_timeout_s):
            self._output.print_info("[TaskMonitor] «task_idle» отложен")
            return "deferred"
        if titles and self._offer is not None:
            self._offer(QUESTION_IDLE, titles)  # 3 задачи кнопками в чат
        elif self._notify is not None:
            self._notify(question)              # тот же вопрос текстом в чат
        return "idle"

    def _offer_of(self, rows: list) -> tuple:
        """(предложение вслух, названия для кнопок) по календарю сегодня."""
        return idle_offer(rows, self._today_events(), datetime.now().astimezone())

    def _today_events(self) -> Optional[list]:
        """Сегодняшние события календаря; None, если календарь не подключён."""
        if self._gcal is None:
            return None
        now = datetime.now().astimezone()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            return self._gcal.list_events_between(
                day_start, day_start + timedelta(days=1))
        except Exception as error:                # нет токена/сети — откат к таблице
            return swallowed("task_monitor.events", error, None)

    def _snapshot(self):
        """Снимок таблицы: (SheetCheck, сырые строки); None при сбое чтения."""
        try:
            rows = self._real_life_sheet().read_all_tasks()
        except Exception as error:                # нет токена/сети
            return swallowed("task_monitor.read", error, None)
        return evaluate(rows), rows

    def _real_life_sheet(self) -> Any:
        """Лениво создаёт читалку real_life_* (тот же OAuth, что календарь)."""
        if self._sheet is None:
            self._sheet = RealLifeSheet()
        return self._sheet

    def _task_handler(self) -> Any:
        """Лениво создаёт матчер+исполнитель названий задач (task_start)."""
        if self._handler is None:
            self._handler = TaskStartHandler()
        return self._handler

    # ---------- Ответ на вопрос ----------

    def _on_idle_answer(self, text: str) -> None:
        """Ответ на «чем занимаешься?»: найти задачу в таблице и запустить."""
        title = self._match_title(self._core(text))
        if title is None:
            self._output.print_info(
                f"[TaskMonitor] В таблице нет задачи под ответ «{text}»")
            self._say(ANSWER_UNKNOWN)
            return
        result = self._task_handler().start_task(title)
        if result.get("ok"):
            if self._record is not None:    # старт по ответу — в статистику
                self._record(TASKSTART_CMD_ID)
            self._output.print_info(
                f"[TaskMonitor] Задача «{title}» запущена "
                f"(строка {result['row']})")
            self._say(f"Задача «{title}» запущена")
        else:
            self._output.print_error(
                f"[TaskMonitor] {result.get('error')}")

    def _match_title(self, phrase: str) -> Optional[str]:
        """Чистый заголовок задачи, похожей на фразу (или None)."""
        if not phrase or not phrase.strip():
            return None
        try:
            event = self._task_handler().find_task_event(phrase)
        except Exception as error:                # сбой календаря/таблицы
            return swallowed("task_monitor.match", error, None)
        if event is None:
            return None
        title = str(event.get("summary") or "").strip()
        return title or None
