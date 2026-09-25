"""Режим разработки, стоп-слова и остановка (миксин оркестратора)."""

import time

from lib.commands_match import _similarity

# Фразы включения режима разработки (детерминированы, без матчера).
# Vosk иногда коверкает окончания: «режим разработке», «режим разработку»,
# «отладка» — поэтому точное вхождение нескольких вариантов ДОПОЛНЯЕТСЯ
# нечётким сходством с основной фразой (difflib ratio).
DEV_MODE_ENABLE_PHRASE = "режим разработки"
DEV_MODE_ENABLE_VARIANTS = (
    "режим разработки",
    "режим разработке",
    "режим разработку",
    "режим разработка",
    "режим разработчика",
    "режим отладки",
    "режим отладке",
    "отладка",
)
DEV_MODE_EXIT_PHRASE = "будильник"
# Порог нечёткого совпадения фразы включения (difflib ratio).
DEV_MODE_FUZZY_RATIO = 0.8


def _is_dev_enable_phrase(low: str) -> bool:
    """Совпадает ли текст с фразой включения dev-режима.

    Точное вхождение одной из фраз-вариантов или нечёткое сходство всей
    фразы с основной — покрывает ошибки распознавания Vosk.
    """
    for phrase in DEV_MODE_ENABLE_VARIANTS:
        if phrase in low:
            return True
    return _similarity(low, DEV_MODE_ENABLE_PHRASE) >= DEV_MODE_FUZZY_RATIO


class OrchestratorSpeechMixin:
    """Миксин Orchestrator: dev-режим, maybe_abort, stop."""

    def _handle_dev_mode_controls(self, text: str) -> bool:
        """Управляющие фразы режима разработки.

        «режим разработки» (и коверкания Vosk: «режим разработке»,
        «отладка» и т.п.) — включить/выключить, «будильник» внутри
        dev-режима — полный выход из приложения (on_exit). Возвращает True,
        если фраза была управляющей и обработана здесь.
        """
        core = self._matcher.core_phrase(text) if self._aliases is not None \
            else text.strip()
        low = (core or text).lower()

        if _is_dev_enable_phrase(low):
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
        что нужно сделать (например, например, «Включи прокси»).
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
