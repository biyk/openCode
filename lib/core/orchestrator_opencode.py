"""Фоновый console opencode оркестратора (миксин)."""

import threading
import time


class OrchestratorOpencodeMixin:
    """Миксин Orchestrator: очередь и воркер фоновых запросов opencode."""

    def _enqueue_opencode(self, text: str, raw: bool = False) -> None:
        """Ставит текст в фоновую очередь console opencode.

        raw=True — dev-режим: текст передаётся модели без BASE_PROMPT-обёртки.
        """
        if self._opencode is None:
            self._output.print_error("[OpenCode] Раннер не настроен")
            return
        self._opencode_queue.put((text, raw))
        self._ensure_opencode_worker()

    def _drain_opencode_queue(self) -> None:
        """Выбрасывает накопленные, но ещё не обработанные запросы opencode."""
        discarded = 0
        while True:
            try:
                self._opencode_queue.get_nowait()
                discarded += 1
            except Exception:
                break
        if discarded:
            self._output.print_debug(
                f"[OpenCode] Отброшено запросов: {discarded}")

    def _ensure_opencode_worker(self) -> None:
        """Запускает воркер, если он ещё не создан."""
        if self._opencode_worker is not None:
            return
        self._opencode_worker = threading.Thread(
            target=self._opencode_worker_loop, daemon=True)
        self._opencode_worker.start()

    def _opencode_worker_loop(self) -> None:
        """Фоновый воркер: обрабатывает запросы из очереди."""
        while True:
            text, raw = self._opencode_queue.get()
            started = time.monotonic()
            try:
                self._opencode_active = True
                label = " (dev)" if raw else ""
                self._output.print_info(
                    f"[OpenCode] Выполняю в фоне{label}: «{text[:60]}...»"
                    if len(text) > 60 else f"[OpenCode] Выполняю{label}: «{text}»"
                )
                if self._abort_playback.is_set():
                    self._output.print_debug(
                        "[OpenCode] Запрос отменён (стоп)")
                    continue
                answer = self._opencode.run(
                    text, abort_event=self._abort_playback, raw=raw)
                if self._abort_playback.is_set():
                    self._output.print_debug(
                        "[OpenCode] Ответ отменён (стоп)")
                    continue
                if not answer:
                    self._output.print_error(
                        "[OpenCode] Пустой ответ агента (возможно, таймаут "
                        "или opencode не смог выполнить команду)")
                    continue
                elapsed = time.monotonic() - started
                # Результат — в консоль (только читаемый итог), подробности — в лог
                self._output.print_info(
                    f"[OpenCode] Итог ({elapsed:.0f}с): {answer}")
                self._output.print_debug(
                    f"[OpenCode] Ответ (сводка): {answer}")
            except Exception as e:
                self._output.print_error(
                    f"[OpenCode] Ошибка фонового запроса: {e}")
            finally:
                self._opencode_active = False
                self._opencode_queue.task_done()
