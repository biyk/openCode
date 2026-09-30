# TOOLTIP: Фоновая (в отдельном потоке) проверка активного окна на «отдых»
"""Опрос модели про активное окно, не блокируя цикл ``task_monitor``.

Медленный/зависший OmniRouter (``classify_until_answer`` крутит до ответа) не
должен занимать поток монитора: иначе он задерживал бы и вопрос «чем ты сейчас
занимаешься?». Поэтому проверка уходит в отдельный daemon-поток, а новый опрос
не стартует, пока предыдущий ещё ждёт ответ (не плодим потоки). Примитивы —
взять заголовок и опросить модель — внедряет вызывающий (фабрика
``task_monitor_launch``); здесь только диспетч потока и озвучка вердикта.
"""

import threading
from typing import Any, Callable, Optional

from lib.core.errors import swallowed


class RestWatch:
    """Однофлаговый диспетчер фоновой проверки активного окна на отдых."""

    def __init__(self, title_fn: Optional[Callable[[], str]],
                 classify_fn: Optional[Callable[[str], Any]],
                 output: Any) -> None:
        self._title_fn = title_fn
        self._classify_fn = classify_fn
        self._output = output
        self._lock = threading.Lock()
        self._running = False

    @property
    def enabled(self) -> bool:
        """Есть ли примитивы окна (без них проверка выключена — сеть не трогать)."""
        return self._title_fn is not None and self._classify_fn is not None

    def check_async(self) -> None:
        """Запускает проверку в отдельном потоке; повтор — только после конца."""
        if not self.enabled:
            return
        with self._lock:
            if self._running:
                return                       # предыдущая ещё ждёт модель
            self._running = True
        threading.Thread(target=self._run, daemon=True,
                         name="task-rest-check").start()

    def _run(self) -> None:
        """Тело потока: заголовок → вердикт модели → озвучить, если отдых."""
        try:
            title = self._title_fn()
            res = self._classify_fn(title)
            if res.is_rest:
                self._output.print_info(
                    f"[TaskMonitor] Отдых: «{title}» ({res.probability}%) "
                    f"{res.explanation}")
        except Exception as error:               # фоновый поток не роняем
            swallowed("task_monitor.rest_window", error)
        finally:
            with self._lock:
                self._running = False


__all__ = ["RestWatch"]
