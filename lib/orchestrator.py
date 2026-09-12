"""Оркестратор обработки голосового ввода (детерминированное ядро).

Решает, на каком уровне обрабатывать распознанный текст: стоп-слово во время
озвучки, готовая команда или запрос к LLM. Сюда же подключаются будущие слои
(мини-LLM, скиллы, большая LLM, модель-контролёр), не затрагивая ядро
распознавания в main.py.
"""

import threading
import time
from typing import Any, Callable, Optional

from lib.commands import CommandMatcher
from lib.output import TranscriptionOutput


class Orchestrator:
    """Детерминированный слой принятия решений для распознанного текста."""

    def __init__(
        self,
        matcher: CommandMatcher,
        output: TranscriptionOutput,
        llm: Any,
        tts: Any,
        stop_words: frozenset[str] = frozenset(
            ("стоп", "останови", "stop", "хватит", "прекрати")
        ),
        suppress_after: float = 0.5,
        clear_speech_buffer: Optional[Callable[[], None]] = None,
    ) -> None:
        self._matcher = matcher
        self._output = output
        self._llm = llm
        self._tts = tts
        self._stop_words = stop_words
        self._suppress_after = suppress_after
        self._clear_speech_buffer = clear_speech_buffer or (lambda: None)
        self._speaking = False
        self._abort_playback = threading.Event()
        self._suppress_until = 0.0

    @property
    def speaking(self) -> bool:
        """Идёт ли сейчас озвучка TTS."""
        return self._speaking

    @property
    def abort_playback(self) -> threading.Event:
        """Событие прерывания синтеза/воспроизведения TTS."""
        return self._abort_playback

    @property
    def suppress_until(self) -> float:
        """Момент (time.monotonic) окончания окна эхо-затишья."""
        return self._suppress_until

    def process_text(self, text: str) -> None:
        """Обрабатывает текст: стоп-слово, команда или запрос к LLM."""
        if time.monotonic() < self._suppress_until:
            return
        if self._speaking:
            self.maybe_abort(text)
            return
        if not self._matcher.has_trigger(text):
            self._output.print_text(text)
            return
        command = self._matcher.find(text)
        if command:
            self._matcher.execute(text)
            self._output.print_text(command)
        else:
            self._output.print_info(f"[LLM] Запрос: {text}")
            answer = self._llm.ask(text)
            if answer:
                self._speaking = True
                self._abort_playback.clear()
                self._speak_async(answer)
            else:
                self._output.print_error("[LLM] Ошибка ответа")
                self._output.print_text(text)

    def maybe_abort(self, text: str) -> bool:
        """Прерывает озвучку, если в тексте есть стоп-слово (целое слово).

        Возвращает True, если озвучка была прервана. Используется для
        финальных и частичных результатов распознавания.
        """
        if not self._speaking:
            return False
        tokens = text.lower().split()
        if not any(token in self._stop_words for token in tokens):
            return False
        self._abort_playback.set()
        self._output.print_info("[TTS] Озвучка прервана")
        return True

    def _speak_async(self, answer: str) -> None:
        """Запускает озвучку в фоне, оставляя цикл распознавания активным."""
        def _play() -> None:
            try:
                self._tts.speak_and_play(answer, abort_event=self._abort_playback)
            except Exception as e:
                self._output.print_error(f"Ошибка озвучки: {e}")
            finally:
                self._on_speaking_finished()

        threading.Thread(target=_play, daemon=True).start()

    def _on_speaking_finished(self) -> None:
        """Сбрасывает флаг озвучки и ставит окно эхо-затишья."""
        self._speaking = False
        self._suppress_until = time.monotonic() + self._suppress_after
        self._clear_speech_buffer()

    def stop(self) -> None:
        """Прерывает активное воспроизведение TTS."""
        self._abort_playback.set()
