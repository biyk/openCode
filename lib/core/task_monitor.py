# TOOLTIP: Фоновый контроль таблицы задач: вопрос вслух и старт по ответу
"""Периодическая проверка real_life_tasks (раз в TASK_MONITOR_INTERVAL_S).

Ни одной запущенной задачи (start_date = 0 у всех строк) — вслух вопрос
«чем ты сейчас занимаешься?»; следующая строка — ответ: к ней дописывается
ключ «начал» → команда taskstart (тот же скрипт); при промахе — `_on_idle_answer`.
Пока идёт «СОН», цикл молчит ЦЕЛИКОМ: и вопроса, и оповещения (§4.3).
Вердикт держит `lib/core/sleep_gate.py`, а не локальное чтение календаря.

Вопрос и сбор ответа — через оркестратор (`ask` из orchestrator_ask), чтобы
реплика пользователя не ушла в пайплайн команд; `recall` убирает реплику
вопроса из Telegram, когда ответа не дождались. Поток свой (как
version_checker), а собирает и запускает монитор `start_task_monitor`.
"""

import threading
from datetime import datetime
from typing import Any, Callable, Optional

from lib.core.errors import swallowed
from lib.core.overtime import OvertimeNotifier
from lib.core.rest_watch import RestWatch
from lib.core.sleep_gate import check_sleeping, today_events
from lib.core.task_pick import TASK_NOT_FOUND_TEXT, TASKSTART_CMD_ID, TASKSTART_KEY
from lib.core.tuning import TASK_ANSWER_TIMEOUT_S, TASK_MONITOR_INTERVAL_S
from lib.monitor import registry
from lib.task_start import TaskStartHandler
from lib.taskflow.real_life_sheet import RealLifeSheet
from lib.taskflow.task_check import evaluate
from lib.taskflow.task_schedule import idle_offer

# Вопрос, когда не запущено ничего (ответ — название задачи из таблицы):
# голосом звучит только вопрос (решение пользователя), «что начать» уходит
# кнопками в Telegram, а текстом — только когда задач-кнопок нет.
QUESTION_IDLE = "Чем ты сейчас занимаешься?"
# Ответ не похож ни на одну задачу: та же фраза, что на промах taskstart.
ANSWER_UNKNOWN = TASK_NOT_FOUND_TEXT


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
                 recall: Optional[Callable[[], int]] = None,
                 sleep_fn: Optional[Callable[[], bool]] = None,
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
        self._recall = recall
        self._sleep_fn = sleep_fn
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
        while not self._stop.is_set():
            registry.report("task_monitor", "Монитор задач", registry.IDLE,
                            f"интервал {self._interval:.0f}с")
            if self._stop.wait(self._interval):
                break
            registry.report("task_monitor", "Монитор задач", registry.WORKING)
            try:
                self.tick()
            except Exception as error:            # цикл не должен умирать
                swallowed("task_monitor.tick", error)

    # ---------- Одна проверка (публично для тестов) ----------

    def tick(self) -> str:
        """Читает таблицу; «СОН» снимает весь цикл, иначе idle — вопрос."""
        if self._fun is not None:
            self._fun()             # дыры календаря молча закрываются каждый цикл
        snapshot = self._snapshot()
        if snapshot is None:
            return "skip"
        check, rows = snapshot
        if self._sleeping():        # до оповещений: спящего не будим (§4.3)
            self._output.print_info("[TaskMonitor] «СОН» — вопрос и оповещения сняты")
            return "sleep"
        if self._overtime is not None:
            self._overtime.check(check)   # и при занятой задаче, не только idle
        if check.idle:
            return self._handle_idle(rows)
        return "busy"

    def _sleeping(self) -> bool:
        """Вердикт «СОН»: липкий кэш гейта, иначе — своё чтение календаря."""
        if self._sleep_fn is not None:
            return bool(self._sleep_fn())
        return bool(self._gcal) and check_sleeping(self._gcal)

    def _handle_idle(self, rows: list) -> str:
        """Idle: вопрос вслух (+кнопки в Telegram); «СОН» снят ещё в tick()."""
        now = datetime.now().astimezone()
        events = today_events(self._gcal, now) if self._gcal else None
        self._rest.check_async()           # окно = отдых? проверить в фоне
        _, titles = idle_offer(rows, events, now)
        # on_expire — снять реплику вопроса: висящие кнопки зовут в чат впустую
        if not self._ask(QUESTION_IDLE, self._on_idle_answer, "task_idle",
                         self._answer_timeout_s, self._recall,
                         prefix=TASKSTART_KEY):
            self._output.print_info("[TaskMonitor] «task_idle» отложен")
            return "deferred"
        if self._offer is not None:
            self._offer(QUESTION_IDLE, titles)  # кнопки; без задач — текст
        elif self._notify is not None:
            self._notify(QUESTION_IDLE)         # чата нет — вопрос в консоль
        return "idle"

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
        """Новый handler на каждый ответ: TaskStartHandler фиксирует now в
        __init__, а монитор живёт весь процесс — кэш ставил бы устаревший
        start_date (зубы: 5 мин → 630). Тестовый handler переиспользуем.
        """
        return self._handler or TaskStartHandler()

    # ---------- Ответ на вопрос ----------

    def _on_idle_answer(self, text: str) -> None:
        """Ответ мимо команды taskstart: найти задачу в таблице и запустить."""
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
            self._output.print_info(f"[TaskMonitor] «{title}» (стр. {result['row']}) запущена")
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
        return str((event or {}).get("summary") or "").strip() or None
