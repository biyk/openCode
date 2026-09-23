"""Режим разработки, стоп-слова и остановка (миксин оркестратора)."""

import time

# Управляющие фразы режима разработки (детерминированы, без матчера).
DEV_MODE_ENABLE_PHRASE = "режим разработки"
DEV_MODE_EXIT_PHRASE = "будильник"


class OrchestratorSpeechMixin:
    """Миксин Orchestrator: dev-режим, maybe_abort, stop."""

    def _handle_dev_mode_controls(self, text: str) -> bool:
        """Управляющие фразы режима разработки.

        «режим разработки» — включить/выключить, «будильник» внутри
        dev-режима — полный выход из приложения (on_exit). Возвращает True,
        если фраза была управляющей и обработана здесь.
        """
        core = self._matcher.core_phrase(text) if self._aliases is not None \
            else text.strip()
        low = (core or text).lower()

        if DEV_MODE_ENABLE_PHRASE in low:
            self._dev_mode = not self._dev_mode
            if self._dev_mode:
                self._output.print_info("[DevMode] Включён")
                self._say("Режим разработки. Все фразы идут напрямую")
            else:
                self._output.print_info("[DevMode] Выключен")
                self._say("Режим разработки выключен")
            return True

        if self._dev_mode and DEV_MODE_EXIT_PHRASE in low:
            self._output.print_info("[DevMode] Выход из приложения")
            if self._on_exit is not None:
                self._on_exit()
            else:
                self._say("Выход не настроен")
            return True

        return False

    def _report_blocked(self, cmd_id: str, missing: list[str]) -> None:
        """Сообщает, каких статусов не хватает (консоль + голос).

        Вместо молчаливого ухода в LLM пользователь слышит,
        что нужно сделать (например, «Включи VPN вручную»).
        """
        names = ", ".join(missing)
        self._output.print_error(f"[Blocked] «{cmd_id}»: нет статуса: {names}")
        message = ". ".join(self._matcher.need_message(n) for n in missing)
        self._speaking = True
        self._abort_playback.clear()
        self._speak_async(message)

    def maybe_abort(self, text: str) -> bool:
        """Прерывает озвучку или ожидающий ответ opencode, если есть стоп-слово.

        Возвращает True, если процесс был прерван. Используется для
        финальных и частичных результатов распознавания.
        """
        if not self._speaking and not self._opencode_active:
            return False
        tokens = text.lower().split()
        if not any(token in self._stop_words for token in tokens):
            return False
        self._abort_playback.set()
        if self._speaking:
            self._output.print_info("[TTS] Озвучка прервана")
        else:
            self._output.print_info("[OpenCode] Ожидаемый ответ отменён")
        return True

    def _on_speaking_finished(self) -> None:
        """Сбрасывает флаг озвучки и ставит окно эхо-затишья."""
        self._speaking = False
        self._suppress_until = time.monotonic() + self._suppress_after
        self._clear_speech_buffer()

    def stop(self) -> None:
        """Прерывает активное воспроизведение TTS и очищает очередь opencode."""
        self._abort_playback.set()
        self._drain_opencode_queue()
