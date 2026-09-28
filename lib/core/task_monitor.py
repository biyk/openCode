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
from typing import Any, Callable, Optional

from lib.core.errors import swallowed
from lib.core.tuning import TASK_ANSWER_TIMEOUT_S, TASK_MONITOR_INTERVAL_S
from lib.task_start import TaskStartHandler
from lib.taskflow.real_life_sheet import RealLifeSheet
from lib.taskflow.task_check import SheetCheck, evaluate

# Вопрос, когда не запущено ничего (ответ — название задачи из таблицы).
QUESTION_IDLE = "Чем ты сейчас занимаешься?"
# Ответ на него не похож ни на одну задачу: произносим и живём дальше.
ANSWER_UNKNOWN = "Такой задачи в списке нет"


class TaskMonitor:
    """Фоновый опрос таблицы задач и вопрос пользователю."""

    def __init__(self, ask: Callable[..., bool], say: Callable[[str], None],
                 output: Any, core: Optional[Callable[[str], str]] = None,
                 sheet: Any = None, handler: Any = None,
                 interval_s: float = TASK_MONITOR_INTERVAL_S,
                 answer_timeout_s: float = TASK_ANSWER_TIMEOUT_S) -> None:
        self._ask = ask
        self._say = say
        self._output = output
        self._core = core or (lambda text: text)
        self._sheet = sheet
        self._handler = handler
        self._interval = interval_s
        self._answer_timeout_s = answer_timeout_s
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
        check = self._check()
        if check is None:
            return "skip"
        if check.idle:
            return self._ask_or_defer(
                QUESTION_IDLE, self._on_idle_answer, "task_idle", "idle")
        return "busy"

    def _ask_or_defer(self, question: str, on_answer: Callable[[str], None],
                      label: str, verdict: str) -> str:
        """Задаёт вопрос; False от оркестратора (уже ждём ответ) — пропуск."""
        if self._ask(question, on_answer, label, self._answer_timeout_s):
            return verdict
        self._output.print_info(f"[TaskMonitor] «{label}» отложен")
        return "deferred"

    def _check(self) -> Optional[SheetCheck]:
        """Снимок таблицы (None — прочитать не удалось, молча пропускаем)."""
        try:
            rows = self._real_life_sheet().read_all_tasks()
        except Exception as error:                # нет токена/сети
            return swallowed("task_monitor.read", error, None)
        return evaluate(rows)

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


def start_task_monitor(worker: Any, output: Any) -> Optional[TaskMonitor]:
    """Собирает и запускает монитор по секции `task_monitor` commands.json.

    Ключи секции: enabled, interval_min, answer_timeout_s; чего нет — берём
    из lib.core.tuning. None — секция выключена.
    """
    config = worker._matcher.get_task_monitor_config()
    if not config.get("enabled"):
        return None
    interval_s = float(config.get("interval_min",
                                  TASK_MONITOR_INTERVAL_S / 60.0)) * 60.0
    output.print_info(
        f"[TaskMonitor] Таблица задач: проверка каждые "
        f"{interval_s / 60.0:.0f} мин")
    monitor = TaskMonitor(
        ask=worker._orchestrator.ask, say=worker._orchestrator.say,
        output=output, core=worker._matcher.core_phrase,
        interval_s=interval_s,
        answer_timeout_s=float(config.get("answer_timeout_s",
                                          TASK_ANSWER_TIMEOUT_S)))
    monitor.start()
    return monitor
