"""Фоновый LLM-детект команды (миксин оркестратора).

Гонка двух провайдеров (OmniRouter + LM Studio) отвечает до минуты:
не запущенный lmstudio даёт ретраи, omni сам по себе долог. Вызванный
синхронно, детект вешал цикл распознавания — новые фразы не доходили до
уровней, пока оркестратор ждал id команды (баг 2026-10-02). Поэтому детект
живёт в собственной очереди с воркером, как console opencode: пока одна
фраза классифицируется, микрофон продолжает работать.

Канал ответа запоминается вместе с запросом: фоновый ответ уйдёт тому, кто
его заказал (чат), а не тому, чей запрос активен в момент готовности
(см. orchestrator_chat). Отмена — по номеру поколения: стоп-слово чистит
очередь, а уже сидящий в classify воркер не исполняет снятую фразу.
"""

import queue
import threading

from lib.core.errors import swallowed


class OrchestratorLlmBgMixin:
    """Миксин Orchestrator: очередь и воркер фоновых LLM-детектов."""

    def _llm_pending(self) -> bool:
        """Есть ли фоновый LLM-детект (в работе или в очереди)."""
        return self._llm_active or not self._llm_queue.empty()

    def _cancel_llm_fallback(self) -> None:
        """Снимает фоновый детект: очередь пуста, запущенный не применится."""
        self._llm_gen += 1
        while True:
            try:
                self._llm_queue.get_nowait()
                self._llm_queue.task_done()
            except queue.Empty:
                break

    def _enqueue_llm_fallback(self, text: str) -> None:
        """Ставит LLM-детект в фон: медленная гонка не блокирует ввод."""
        self._llm_queue.put(
            (text, getattr(self, "_reply", None), self._llm_gen))
        if self._llm_worker is None:
            self._llm_worker = threading.Thread(
                target=self._llm_fallback_worker_loop, daemon=True)
            self._llm_worker.start()

    def _llm_fallback_worker_loop(self) -> None:
        """Фоновый воркер детекта: классификация без лока, применение — в локе."""
        while True:
            text, reply, gen = self._llm_queue.get()
            try:
                self._llm_active = True
                if gen != self._llm_gen:
                    self._output.print_debug(
                        f"[LLM] Фоновый детект снят (стоп): «{text[:40]}»")
                    continue
                if self._run_llm_fallback(
                        text, reply=reply,
                        cancelled=lambda: gen != self._llm_gen):
                    continue
                if gen != self._llm_gen:
                    continue
                with self._input_lock:
                    prev, self._reply = self._reply, reply
                    try:
                        self._llm_fallback_miss(text)
                    finally:
                        self._reply = prev
            except Exception as e:
                swallowed("orchestrator.llm_bg", e)
            finally:
                self._llm_active = False
                self._llm_queue.task_done()
