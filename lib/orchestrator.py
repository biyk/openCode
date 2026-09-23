"""Оркестратор обработки голосового ввода (детерминированное ядро).

Решает, на каком из трёх уровней обрабатывать распознанный текст:
1. commands.json (дословное совпадение + алиасы),
2. mini-LLM (интеллектуальный классификатор команд),
3. console opencode (opencode-cli в cli/, использует скиллы).

Большой чат LLM убран: фолбэк уходит в консольный opencode, который сам
выполняет команду и озвучивает результат через скилл speak-answer.
"""

import queue
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

from lib.aliases import AliasStore
from lib.commands import CommandMatcher
from lib.opencode_cli import OpenCodeCliRunner
from lib.orchestrator_memory import OrchestratorMemoryMixin
from lib.orchestrator_opencode import OrchestratorOpencodeMixin
from lib.orchestrator_speech import OrchestratorSpeechMixin
from lib.output import TranscriptionOutput

# Сколько последних строк потока держим для поиска команды уровня
# commands.json (концепция «трёх строк»: над ключом / с ключом / после ключа).
COMMAND_WINDOW_SIZE = 4


class Orchestrator(
    OrchestratorMemoryMixin,
    OrchestratorOpencodeMixin,
    OrchestratorSpeechMixin,
):
    """Детерминированный слой принятия решений для распознанного текста."""

    def __init__(
        self,
        matcher: CommandMatcher,
        output: TranscriptionOutput,
        tts: Any,
        stop_words: frozenset[str] = frozenset(
            ("стоп", "останови", "stop", "хватит", "прекрати")
        ),
        suppress_after: float = 0.5,
        clear_speech_buffer: Optional[Callable[[], None]] = None,
        intent: Any = None,
        aliases: Optional[AliasStore] = None,
        opencode: Optional[OpenCodeCliRunner] = None,
        on_exit: Optional[Callable[[], None]] = None,
    ) -> None:
        self._matcher = matcher
        self._output = output
        self._tts = tts
        self._stop_words = stop_words
        self._suppress_after = suppress_after
        self._clear_speech_buffer = clear_speech_buffer or (lambda: None)
        self._intent = intent or None
        self._aliases = aliases or None
        self._opencode = opencode or None
        self._on_exit = on_exit or None
        self._dev_mode = False
        self._speaking = False
        self._abort_playback = threading.Event()
        self._suppress_until = 0.0
        self._last_resolution: Optional[tuple[str, str]] = None
        self._opencode_queue: queue.Queue[tuple[str, bool]] = queue.Queue()
        self._opencode_worker: Optional[threading.Thread] = None
        self._opencode_active = False
        self._window: deque[str] = deque(
            maxlen=COMMAND_WINDOW_SIZE)

    @property
    def dev_mode(self) -> bool:
        """Включён ли режим разработки (все фразы → модель напрямую)."""
        return self._dev_mode

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
        if self._opencode_active and self.maybe_abort(text):
            # Пока opencode думает, стоп-слово только отменяет ожидаемый ответ
            return
        if self._handle_dev_mode_controls(text):
            return
        if self._dev_mode:
            # Режим разработки: все фразы напрямую в модель, без матчера.
            self._output.print_text(text)
            self._output.print_info(
                "[DevMode] Фраза передана в модель напрямую")
            self._enqueue_opencode(text, raw=True)
            return
        # Сначала выводим распознанный текст в консоль и лог
        self._output.print_text(text)
        # 0. Мета-команды обучения алиасов («запомни»/«забудь»).
        if (self._aliases is not None and self._matcher.has_trigger(text)
                and self._handle_memory_command(text)):
            return
        # 1. Команды commands.json — концепция «трёх строк».
        self._window.append(text)
        cmd_id, settings, wait = self._matcher.find_command(
            list(self._window))
        if wait:
            # Ключ есть, команды вокруг него нет — ждём следующую строку.
            self._output.print_debug(
                "[Command] Ключ без команды — ждём следующую строку")
            return
        blocked: list[tuple[str, list[str]]] = []
        if cmd_id is not None:
            missing = self._matcher.missing_requires(cmd_id)
            if not missing:
                self._output.print_info(
                    f"[Command] Распознана команда: {cmd_id}"
                    + (f" (настройки: {', '.join(settings)})"
                       if settings else ""))
                self._execute_with_settings(cmd_id, settings)
                self._window.clear()
                return
            blocked = [(cmd_id, missing)]
            self._window.clear()
        # Команды из commands.json нет (или она заблокирована) — дальше
        # старые уровни: алиасы/intent/opencode (переделываются позже).
        if not self._matcher.has_trigger(text):
            return
        literal_id = cmd_id  # найденная (даже заблокированная) команда
        # 1.5. Известное коверканье из базы алиасов — без вызова LLM.
        # Переделывается позже; пока работает как раньше (когда шага 1 нет).
        if cmd_id is None and self._aliases is not None:
            core = self._matcher.core_phrase(text)
            alias_id = self._aliases.resolve(core)
            if alias_id is not None:
                missing = self._matcher.missing_requires(alias_id)
                if not missing:
                    self._output.print_info(
                        f"[Alias] Распознана команда: {alias_id}")
                    self._aliases.bump(core)
                    self._matcher.execute_by_id(alias_id)
                    return
                blocked = [(alias_id, missing)]
        # 2. Не дословно — мини-LLM классификатор команд.
        if self._intent is not None:
            detected = self._intent.detect(text, self._llm_context(blocked))
            if detected is not None:
                self._output.print_info(
                    f"[Mini] Распознана команда «{detected}»"
                )
                if self._matcher.execute_by_id(detected):
                    self._output.print_text(detected)
                    self._remember_candidate(text, detected, literal_id)
                    return
                missing = self._matcher.missing_requires(detected)
                if missing:
                    self._report_blocked(detected, missing)
                    return
                self._output.print_error(
                    f"[Mini] Команда «{detected}» не найдена"
                )
                return
        self._output.print_debug(
            f"[OpenCode Decision] No literal, no alias, no intent match. "
            f"Sending to opencode-cli. Text: {text}"
        )
        self._output.print_info("... отправка запроса в opencode-cli (фон)")
        self._enqueue_opencode(text)

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
